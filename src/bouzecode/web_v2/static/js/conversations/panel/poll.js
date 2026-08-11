// Poll de /api/sessions/<key>/blocks : insertion des blocs rendus par le backend,
// placeholder d'état tant qu'aucun bloc n'existe, et cadence adaptative.

import { node } from "../dom.js";
import { openTabs } from "../state.js";
import { PHASE_BADGE } from "../badges.js";
import { pairToolBlocks } from "./tool_blocks.js";
import { renderQuestion } from "./question.js";
import { renderMeta } from "./meta.js";
import { pollPartial } from "./streaming.js";
import { maybeEnableRecap } from "../recap/view.js";
import { formatEventTime, formatEventTimeTooltip } from "../../time_format.js";
import { t, applyDom } from "../../i18n/index.js";

// Hydrate les marqueurs temporels rendus VIDES par le backend : chaque
// <span class="event-time" data-iso="…"> (marqueur inline sous-agent) ou
// <span class="conv-item-time" data-iso="…"> (sidebar) est rempli côté client
// depuis l'ISO UTC → heure LOCALE via le helper unique. textContent = heure
// formatée, title = ISO complet (tooltip). Idempotent : re-remplit à chaque appel.
function hydrateEventTimes(root) {
  if (!root) return;
  root.querySelectorAll(".event-time[data-iso], .conv-item-time[data-iso]").forEach((el) => {
    const iso = el.getAttribute("data-iso") || "";
    el.textContent = formatEventTime(iso);
    el.title = formatEventTimeTooltip(iso);
  });
}

// --- Polling /blocks (calqué sur session.js) --------------------------------

// Placeholder d'état affiché dans le corps d'un onglet TANT QU'aucun vrai bloc n'a été
// rendu (session pas encore écrite, agent bloqué/mort, ou onglet de lancement). Sans lui,
// l'onglet restait visuellement VIDE — permanent si l'agent ne spawnait/n'écrivait jamais
// (cas vécu : ticket « Suite du ticket… » vide depuis 3 jours). Idempotent : ne crée
// qu'une seule div et se contente d'en mettre le texte à jour aux polls suivants.
function setEmptyState(entry, msg) {
  // Un vrai bloc déjà rendu ⇒ pas de placeholder (poll a purgé via clearEmptyState).
  // NB : on itère sur `children` (enfants directs) plutôt que `:scope > …` — ce dernier
  // sélecteur n'est pas fiable sous happy-dom (les tests), et l'itération est portable.
  const kids = [...entry.conv.children];
  if (kids.some((el) => !el.classList.contains("conv-empty-state"))) return;
  let el = kids.find((n) => n.classList.contains("conv-empty-state"));
  if (!el) el = node(entry.conv, "div", "conv-empty-state");
  if (el.textContent !== msg) el.textContent = msg;
}

function clearEmptyState(entry) {
  [...entry.conv.children]
    .filter((el) => el.classList.contains("conv-empty-state"))
    .forEach((el) => el.remove());
}

// Ce qu'on écrit dans un corps ENCORE VIDE. La PHASE prime sur l'état, exactement comme
// dans le badge de la sidebar (cf. badge()/PHASE_BADGE) : « en cours » est vrai mais muet
// pendant les secondes de démarrage puis d'attente du modèle.
//
// La phase arrive dans `/api/sessions/<key>/blocks`, donc au rythme de poll() — 1,5 s. Elle
// était SERVIE et JETÉE : le corps ne lisait que `status.state`, si bien que la seule voie
// vers ces libellés restait `/api/agents/tree`, poll à 8 s derrière un cache de 10 s.
// Mesuré le 2026-08-03 : phase connue du serveur à 8,6 s, affichée à 11,9 s. Même source,
// même vocabulaire, six fois plus vite.
// Les libellés de phase sont écrits en minuscule (ils servent aussi de pastille, au fil
// d'une phrase) : en tête de placeholder ils prennent une capitale.
function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function waitingMessage(state, phase) {
  // PHASE_BADGE porte des CLÉS i18n, pas des libellés : le vocabulaire des phases est
  // partagé avec la sidebar et les chips (i18n/*/state.js), jamais réécrit ici.
  const known = PHASE_BADGE[phase];
  if (known) return capitalize(t(known[0]));
  if (state === "starting") return t("panel.waiting_starting");
  if (state === "running" || state === "awaiting_input" || state === "awaiting_plan_validation") {
    return t("panel.waiting_content");
  }
  return t("panel.waiting_empty");
}

// Ce qu'on écrit dans le corps d'un onglet de LANCEMENT, où il n'y a par construction aucune
// session à streamer. Le serveur SAIT pourtant ce qu'il est en train de faire et le NOMME :
// `git worktree add` (mesuré sur ce poste : 1,1 s à chaud, 20,6 s à froid, jusqu'à ~55 s quand
// l'antivirus inspecte les 1431 fichiers du checkout), puis `uv sync`, puis le spawn.
// Le corps affichait à la place une phrase FIGÉE, écrite en dur, identique de la première à la
// cinquante-cinquième seconde : l'utilisateur attendait sans savoir pourquoi, ni si ça avançait.
// Même canal que pour un agent déjà né (`/blocks`, 1,5 s) et MÊMES MOTS que la sidebar et l'API
// (launch_phase.LABELS) — aucun libellé n'est réécrit ici, sinon les surfaces divergeraient.
// Phases de lancement servies en CLÉ par le serveur (`status.phase`) : les mots vivent
// dans i18n/*/state.js. Une phase absente de cette liste retombe sur le `phase_label`
// du serveur — jamais une clé crue à l'écran.
const LAUNCH_PHASES = new Set([
  "provisioning_worktree", "syncing_venv", "spawning",
  "reisolating", "venv_ready", "venv_failed",
]);

async function launchingMessage(key) {
  const resp = await fetch(`/api/sessions/${key}/blocks`).catch(() => null);
  if (!resp || !resp.ok) return t("panel.preparing_conversation");
  const data = await resp.json().catch(() => ({}));
  const status = data.status || {};
  const phase = status.phase || "";
  const label = LAUNCH_PHASES.has(phase) ? t("phase." + phase) : (status.phase_label || "");
  if (!label) return capitalize(t("phase.launching_fallback"));
  // `phase_detail` porte la base du worktree puis, en cas de reprise, « essai 2/3 échoué… » :
  // c'est ce qui distingue un provisionnement lent d'un serveur bloqué. Texte LIBRE du
  // serveur (compteurs, nom de branche) : il n'y a pas de clé à traduire côté client.
  const detail = status.phase_detail ? ` — ${status.phase_detail}` : "";
  return capitalize(label) + "…" + detail;
}

export async function poll(key) {
  const entry = openTabs.get(key);
  if (!entry) return; // onglet fermé
  // Onglet de LANCEMENT (launching/<ticket>) : aucune session à streamer tant que
  // l'agent n'a pas spawné. On ne martèle pas /api/sessions (404) — on attend que
  // refreshList → remapLaunchingTabs bascule l'onglet sur agent/<id> (vraie session).
  // Idem pour un onglet ouvert sur un node OPTIMISTE (optimistic:<ts>-<rand>) : la
  // vraie session n'existe pas encore → /api/sessions/optimistic:.../blocks = 404.
  // reconcileOptimistic()/retargetTab() rebranchera l'onglet sur la vraie key au spawn.
  if (key.startsWith("optimistic:")) {
    setEmptyState(entry, t("panel.preparing_conversation"));
    clearTimeout(entry.poller);
    entry.poller = setTimeout(() => poll(key), 1500);
    return;
  }
  // Onglet de LANCEMENT : toujours rien à streamer, mais `/blocks` répond désormais la PHASE
  // en cours pour cette clé (cf. routes/sessions._launching_blocks) au lieu d'un 404.
  if (key.startsWith("launching/")) {
    const message = await launchingMessage(key);
    if (!openTabs.has(key)) return; // onglet fermé pendant le fetch
    setEmptyState(entry, message);
    clearTimeout(entry.poller);
    entry.poller = setTimeout(() => poll(key), 1500);
    return;
  }
  // Garde de réentrance : un poll(key) peut être (ré)lancé manuellement (reprise
  // via bouton question, activation d'onglet…) ALORS qu'un poll setTimeout est déjà
  // en vol pour la même key. Les deux fetcheraient `after=${entry.nextIndex}` avec le
  // MÊME nextIndex (mis à jour seulement APRÈS l'await, plus bas) → mêmes blocks
  // insérés 2× → bulle dupliquée. On ne laisse jamais 2 corps de poll s'exécuter
  // concurremment pour une même key.
  if (entry.polling) return;
  entry.polling = true;
  try {
    const resp = await fetch(`/api/sessions/${key}/blocks?after=${entry.nextIndex}`);
    if (resp.ok) {
      const data = await resp.json();
      const pinned = entry.conv.scrollTop + entry.conv.clientHeight >= entry.conv.scrollHeight - 40;
      // Un vrai bloc message complet arrive : retire le bloc streaming provisoire
      // (le message rendu le remplace) AVANT d'insérer, pour éviter le doublon.
      if (data.blocks.length) {
        clearEmptyState(entry);
        entry.conv.querySelectorAll(".streaming-block, .streaming-thinking, .streaming-tool").forEach((el) => el.remove());
        const echo = entry.conv.querySelector(".optimistic-echo");
        if (echo) echo.remove();
      }
      data.blocks.forEach((b) => entry.conv.insertAdjacentHTML("beforeend", b.html));
      // Les marqueurs inline sous-agents portent une heure VIDE (data-iso) : le
      // backend ne cuit plus l'heure UTC. On la formate ici en heure locale via
      // le helper unique → même heure que la sidebar pour le même started_at.
      hydrateEventTimes(entry.conv);
      // Même geste pour la LANGUE : le chrome de ces blocs (« réponse finale »,
      // « résultat X — N car. ») arrive du serveur avec sa clé et son texte anglais.
      // Un utilisateur en français doit le lire en français dès l'insertion, sans
      // attendre une bascule. Les clés restent dans le DOM, donc l'opération est
      // idempotente et une bascule ultérieure les réécrira aussi.
      if (data.blocks.length) applyDom(entry.conv);
      if (data.blocks.length) {
        entry.nextIndex = data.total;
        pairToolBlocks(entry.conv);
        if (pinned) entry.conv.scrollTop = entry.conv.scrollHeight;
      }
      const st = (data.status && data.status.state) || "cli";
      entry.lastState = st;
      // Aucun bloc jamais rendu dans ce corps ⇒ afficher un état lisible plutôt qu'un
      // vide muet. Le message REFLÈTE l'état réel (pas de faux « préparation ») : un
      // agent démarrant, un agent terminé sans contenu, ou une attente indéterminée.
      if (!data.blocks.length) {
        setEmptyState(entry, waitingMessage(st, (data.status && data.status.phase) || ""));
      }
      maybeEnableRecap(entry, key);
      renderMeta(entry, data);
      renderQuestion(entry, data.status);
    }
  } catch (_) { /* réseau : on retentera */ }
  finally { entry.polling = false; }
  const active = entry.lastState === "running" || entry.lastState === "awaiting_input" || entry.lastState === "awaiting_plan_validation";
  // Terminal (finished/cli) : on espace fortement /blocks mais on ne s'arrête PAS
  // (détecteur de reprise via /continue). Actif : cadence normale, ralentie si onglet caché.
  let delay;
  if (active) delay = document.visibilityState === "hidden" ? 5000 : 1500;
  else delay = 15000;
  clearTimeout(entry.poller);
  entry.poller = setTimeout(() => poll(key), delay);
  // Reprise d'une génération après un état non-streaming : relancer pollPartial.
  if (entry.lastState === "running" && !entry.partialActive && document.visibilityState !== "hidden") {
    entry.partialActive = true;
    pollPartial(key);
  }
}
