// Talonnage du DÉMARRAGE et rebranchement des onglets provisoires.
//
// Un onglet peut naître sur une clé qui ne désigne aucune session : `optimistic:<ts>`
// (avant même la réponse du dispatch) ou `launching/<ticket>` (provisioning en cours).
// Ces deux clés doivent être RE-CIBLÉES en place vers la vraie `agent/<id>` dès que
// l'agent existe — sinon l'onglet reste vide à jamais et l'agent réel s'ouvre dans un
// SECOND onglet.

import { NODES, openTabs, activeKey, setActiveKey, optimisticNodes, setOptimisticNodes } from "../state.js";
import { refreshList } from "../sidebar/list.js";
import { activateTab } from "../panel/tabs.js";
import { poll } from "../panel/poll.js";
import { pollPartial } from "../panel/streaming.js";

// Un onglet ouvert en réactivité "à la volée" (defer) porte la clé provisoire
// `launching/<ticket_id>` (aucun agent spawné encore). Dès que le worktree+venv
// sont prêts, le serveur spawne l'agent : le node launching DISPARAÎT du snapshot
// (dédup have_ticket côté fleet) et un vrai node `agent/<id>` portant le MÊME
// ticket_id apparaît. On RENOMME alors la clé de l'onglet en place — sinon
// l'onglet provisioning resterait orphelin (plus jamais dans NODES) et l'agent
// réel s'ouvrirait dans un SECOND onglet. On relance poll/pollPartial sur la vraie
// clé pour streamer la session (l'onglet launching n'avait rien à streamer).
export function remapLaunchingTabs() {
  for (const [oldKey, entry] of [...openTabs]) {
    if (!oldKey.startsWith("launching/")) continue;
    const tid = oldKey.slice("launching/".length);
    const real = NODES.find((n) => n.ticket_id === tid && (n.key || "").startsWith("agent/"));
    if (!real) continue;
    const newKey = real.key;
    if (newKey === oldKey || openTabs.has(newKey)) continue;
    openTabs.delete(oldKey);
    entry.key = newKey;
    if (entry.tab) entry.tab.dataset.key = newKey;
    if (entry.panel) entry.panel.dataset.key = newKey;
    entry.nextIndex = 0;        // re-stream la vraie session depuis le début
    entry.partialActive = true;
    openTabs.set(newKey, entry);
    if (activeKey === oldKey) setActiveKey(newKey);
    poll(newKey);
    pollPartial(newKey);
  }
}

// Réconciliation : appelée par refreshList AVANT renderList. Un optimiste dont le
// vrai node est arrivé (même title_full = 1er message user = le prompt) est retiré
// de la vue ; le renderList qui suit dans refreshList détruit proprement son row
// (le vrai a pris la place, même section « En cours »), sans doublon ni flash.
// Re-cible un onglet ouvert de oldKey vers newKey EN PLACE (sans recréer d'onglet) :
// l'onglet placeholder ouvert sur une session inexistante (poll vide à jamais) est
// ré-hydraté vers la VRAIE session dès que le vrai agent spawn. On arrête les pollers
// courants (qui portent oldKey en closure), on ré-indexe l'entrée dans openTabs sous
// newKey, on repart de nextIndex=0 (session différente) et on relance poll/pollPartial
// avec newKey. Un clic sur cet onglet montre alors le contenu réel, sans doublon.
export function retargetTab(oldKey, newKey) {
  const entry = openTabs.get(oldKey);
  if (!entry) return;
  clearTimeout(entry.poller);
  clearTimeout(entry.partialPoller);
  openTabs.delete(oldKey);
  entry.key = newKey;
  entry.nextIndex = 0;
  entry.lastState = "cli";
  entry.partialActive = true;
  // Autre session, donc autre question : la signature du bloc question doit repartir de zéro,
  // sinon renderQuestion croirait n'avoir rien à reconstruire.
  entry.questionSignature = "";
  if (entry.input) entry.input.id = "conv-input-" + newKey;
  openTabs.set(newKey, entry);
  if (activeKey === oldKey) setActiveKey(newKey);
  poll(newKey);
  pollPartial(newKey);
}

// Talonnage du DÉMARRAGE. Un dispatch part en `defer` : le serveur répond AVANT que l'agent
// existe, puis l'agent traverse deux phases muettes — « démarrage » (worktree, venv, boot du
// process) puis « attente du modèle » (première requête, écriture du cache). Ces deux
// transitions n'étaient visibles qu'au tick de 8 s de la liste : c'est très exactement le
// « 10 s, puis encore 10 s » rapporté.
// Mesuré le 2026-08-03 sur le parc réel : node présent côté serveur à 8,6 s / affiché à
// 11,9 s ; puis phase « attente du modèle » connue à 35,5 s / affichée à 39,0 s.
// On rafraîchit donc à 1 s pendant TOUTE la fenêtre de démarrage — de l'envoi jusqu'à ce que
// l'agent n'ait plus de phase à annoncer — puis on rend la main au tick normal.
const CHASE_INTERVAL_MS = 1000;
// Plafond de sécurité : un provisioning worktree+venv peut dépasser la minute, mais un
// talonnage sans fin sur un dispatch mort martèlerait le serveur à vie.
const CHASE_TIMEOUT_MS = 180000;

// Vrai tant que ce node a quelque chose de neuf à annoncer sur son démarrage. Une phase non
// vide EST le signal : le backend ne la sert que pendant les secondes où l'état ordinaire ne
// dit rien (cf. store.demarrage_phase), et la vide dès qu'un état suffit.
function stillStarting(node) {
  return !!node && (!!node.phase || node.state === "starting" || node.state === "provisioning");
}

export async function chaseLaunch(optKey, ticketId) {
  const deadline = Date.now() + CHASE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, CHASE_INTERVAL_MS));
    // refreshList appelle reconcileOptimistic : après elle, l'optimiste a disparu si son
    // vrai node est arrivé. On rafraîchit AVANT de tester, sinon on sort un tour trop tôt.
    await refreshList(true);
    if (optimisticNodes.some((o) => o.key === optKey)) continue; // agent pas encore né
    // Né : on continue à talonner tant qu'il annonce une phase de démarrage.
    const real = NODES.find((n) => !n._optimistic && n.ticket_id === ticketId);
    if (!stillStarting(real)) return;
  }
}

// Réconciliation : appelée par refreshList AVANT renderList. Pour chaque optimiste dont
// le vrai node est arrivé (même title_full = 1er message user = le prompt), on le retire
// de la vue. Si un onglet placeholder est ouvert sur sa key optimiste, on le RE-CIBLE
// in-place vers la vraie key (pas de 2e onglet parasite, pas d'onglet vide à jamais).
export function reconcileOptimistic() {
  if (!optimisticNodes.length) return;
  setOptimisticNodes(optimisticNodes.filter((o) => {
    const real = NODES.find(
      (n) =>
        !n._optimistic &&
        ((o.ticket_id && n.ticket_id === o.ticket_id) ||
          n.title_full === o.title_full),
    );
    if (!real) return true; // pas encore arrivé : on garde l'optimiste
    if (openTabs.has(o.key)) {
      if (openTabs.has(real.key)) {
        // Le vrai onglet existe déjà (ouvert entre-temps) : on détruit juste le
        // placeholder pour ne pas laisser de doublon vide. Destruction directe
        // (pas closeTab) pour éviter la récursion refreshList → reconcileOptimistic.
        const stale = openTabs.get(o.key);
        clearTimeout(stale.poller);
        clearTimeout(stale.partialPoller);
        if (stale.tab && stale.tab.parentNode) stale.tab.remove();
        if (stale.panel && stale.panel.parentNode) stale.panel.remove();
        openTabs.delete(o.key);
        if (activeKey === o.key) activateTab(real.key);
      } else {
        retargetTab(o.key, real.key);
      }
    }
    return false; // vrai node arrivé : on retire l'optimiste de la vue
  }));
}
