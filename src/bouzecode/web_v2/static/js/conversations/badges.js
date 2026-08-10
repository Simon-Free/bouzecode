// Pastilles d'état et de PHASE : le vocabulaire visuel unique de la page.
// Sidebar (cartes), chips de sous-agents et ligne meta du panneau lisent tous ces
// mêmes tables — c'est ce qui garantit qu'un agent ne peut pas être « terminé » ici
// et « planté » ailleurs.

import { node, agentId } from "./dom.js";
import { NODES } from "./state.js";

// PHASES DE DÉMARRAGE — servies par le backend (`n.phase`, cf. store.demarrage_phase).
// « en cours » ne dit rien pendant les ~10 s qui séparent le clic du premier mot : 4 s de
// démarrage puis 6 s d'attente du modèle. L'utilisateur croit que ça a planté. Chaque phase
// a sa PROPRE couleur pour qu'on distingue d'un coup d'œil « ça se prépare » de « ça
// travaille » — et le libellé de l'attente explique POURQUOI la première réponse est la plus
// lente, ce qui est la question la plus posée. Vaut aussi à la reprise : un tour 12 qui
// attend son modèle affiche la même chose qu'un tour 1.
export const PHASE_BADGE = {
  demarrage: ["démarrage de l'agent…", "st-boot",
              "Un processus neuf se lance : chargement du harnais et lecture du projet."],
  attente_modele: ["le modèle lit votre demande…", "st-wait",
                   "La première réponse est plus longue : le modèle met votre contexte en "
                   + "mémoire. Les suivantes seront nettement plus rapides."],
};

const STATE_BADGE = {
  running: ["en cours", "st-run"],
  starting: ["démarrage…", "st-run"],
  // Ticket en cours de lancement (worktree/venv/spawn en fond, aucun agent encore). Ce badge
  // était DÉCRIT par le commentaire de isActiveState mais absent de cette table : l'interface
  // affichait donc la chaîne brute « provisioning » en gris neutre. La phase précise (création
  // du worktree, installation uv, démarrage) arrive à part, dans la chip d'activité.
  provisioning: ["préparation…", "st-run"],
  awaiting_input: ["à répondre", "st-input"],
  awaiting_plan_validation: ["plan à valider", "st-input"],
  idle: ["chaud", "st-warm"],
  finished: ["terminé", "st-ok"],
  // Vivacité `crashed` SERVIE par le backend : mort PROUVÉE sans clôture (ni FinalAnswer,
  // ni verdict). Certitude → libellé affirmatif, même mot que le board (« planté »).
  crashed: ["planté", "st-ko"],
  waiting_children: ["⏳ orchestre", "st-run"],
  cli: ["cli", "st-cli"],
  ko: ["KO", "st-ko"],
  archived: ["archivé", "st-cli"],
};

// Un node "terminé" (finished) qui a des ENFANTS encore vivants n'est PAS fini : c'est un
// manager qui a clos son tour EXPRÈS (pour être ré-invocable par le wake) et attend ses enfants.
// L'afficher "terminé" le fait paraître mort dans la sidebar → on renvoie un état synthétique
// "waiting_children" (badge « ⏳ orchestre » pulsant) tant qu'un enfant tourne encore.
const TERMINAL_STATES = new Set(["finished", "cli", "crashed", "error"]);
function hasLiveChildren(n) {
  const id = n.agent_id || agentId(n.key);
  if (!id) return false;
  return NODES.some((c) => {
    const p = c.parent;
    if (!p || p.startsWith("dispatcher:")) return false;
    if (p !== id && agentId(p) !== id) return false;
    return !TERMINAL_STATES.has(c.state) && !c.suspect_dead;
  });
}
export function effectiveState(n) {
  // Le VERDICT du validateur prime pour un node terminé : un finished au verdict KO
  // n'est PAS un succès → état synthétique "ko" (badge rouge), jamais vert. Un node
  // archivé passe en "archived" (gris neutre). Centralisé ici : sidebar (createGroup /
  // updateGroup) ET chip sous-agent (renderSubagents) héritent tous du même verdict.
  if (n.archived) return "archived";
  if (n.verdict === "KO") return "ko";
  // VIVACITÉ SERVIE PAR LE BACKEND (fleet._node → liveness.classify_agent) : elle croise pid
  // vivant + close_reason + final_answer + verdict, là où `n.state` ne dit que « la session
  // est close ». Un agent mort sans clôture prouvée s'affichait donc « terminé » ici pendant
  // que le board disait « planté ». Le front ne redérive RIEN : il obéit à `n.liveness`.
  if (n.liveness === "crashed") return "crashed";
  if (n.state === "finished" && hasLiveChildren(n)) return "waiting_children";
  return n.state;
}
// Un node ACTIF pour le sectionnement : running, ou manager en attente de ses enfants
// (waiting_children). Un manager en attente va donc dans « ● En cours », pas « Terminés »,
// cohérent avec son badge « ⏳ orchestre ».
export function isActiveState(n) {
  const s = effectiveState(n);
  // "starting" = agent au process VIVANT dont la session n'est pas encore écrite
  // (premier tour en cours) → section « En cours », badge démarrage… ; bascule sur
  // "running" au polling suivant dès que la session existe.
  // "provisioning" = ticket en cours de lancement (worktree/venv/spawn en fond, pas
  // encore d'agent) → node synthétique injecté par le serveur ; va en « En cours »
  // avec un badge « préparation… » jusqu'à ce que le vrai node agent le remplace.
  return s === "running" || s === "waiting_children" || s === "starting" || s === "provisioning";
}

export function badge(el, state, suspectDead, opts) {
  const compact = opts && opts.compact;
  let [label, cls] = STATE_BADGE[state] || [state || "?", "st-cli"];
  let tip = label;
  // La PHASE prime sur l'état quand elle existe : « en cours » est vrai mais muet pendant
  // les secondes de démarrage et d'attente du modèle. Le backend ne la sert QUE là
  // (cf. store.demarrage_phase) ; ailleurs elle est vide et l'état reprend la main.
  const phase = opts && opts.phase;
  if (phase && PHASE_BADGE[phase]) {
    const [phLabel, phCls, phTip] = PHASE_BADGE[phase];
    label = phLabel;
    cls = phCls;
    tip = phTip;
  }
  // Deux niveaux de certitude, JAMAIS confondus (et jamais « terminé ») :
  //  - state === "crashed" : la vivacité backend PROUVE la mort sans clôture → « planté ».
  //  - suspectDead        : on ne SAIT pas (session close proprement mais 0 tour et rc≠0)
  //                         → « mort ? », le point d'interrogation dit l'incertitude.
  // La certitude prime sur le soupçon : inutile de demander « mort ? » quand c'est prouvé.
  if (state === "crashed") {
    tip = "Agent mort sans clôture prouvée (ni FinalAnswer, ni verdict) : à relancer.";
  } else if (suspectDead) {
    [label, cls] = ["mort ?", "st-ko"];
    // Règle transverse : une alerte (rouge/ambre) ne doit JAMAIS être un dot seul.
    // On explicite le critère qui a déclenché l'alerte dans le tooltip.
    tip = "Agent suspecté mort : terminé sans aucun tour et code de sortie non nul.";
  }
  // Une phase est un état VIVANT : le point bat, comme pour « en cours ».
  const enPhase = !!(phase && PHASE_BADGE[phase]);
  const pulse = (state === "running" || state === "waiting_children" || enPhase) && !suspectDead
    ? " pui-dot--pulse" : "";
  // Anti-dot-seul : en variante compacte on masque normalement le libellé (dot + tooltip),
  // MAIS un état d'alerte (mort prouvée OU suspectée) force TOUJOURS l'affichage du libellé.
  // Une PHASE force aussi le libellé : elle n'existe que pour expliquer une attente, et un
  // point de couleur muet n'explique rien — c'était le défaut à corriger. Elle est brève et
  // s'efface d'elle-même, donc elle n'encombre pas durablement la liste.
  const showLabel = !compact || suspectDead || state === "crashed" || enPhase;
  const b = node(el, "span", `badge ${cls}${compact && !showLabel ? " badge--compact" : ""}`, "");
  b.title = tip; // tooltip (utile surtout en variante compacte : dot seul)
  node(b, "span", `pui-dot${pulse}`);
  if (showLabel) node(b, "span", null, label);
  return b;
}

// Construit un <span.badge …> détaché (mêmes classes/structure que badge()).
export function buildBadge(state, suspectDead, opts) {
  const tmp = document.createElement("span");
  badge(tmp, state, suspectDead, opts);
  return tmp.firstChild;
}

// Libellé lisible d'un état pour le tooltip de la carte (= sa DESCRIPTION accessible, lue par
// les lecteurs d'écran et les snapshots d'accessibilité). Il doit dire EXACTEMENT ce que dit le
// badge de la même carte : c'est ici que « terminé · branche … » contredisait un badge « mort ? ».
export function stateTooltipLabel(eff, suspectDead) {
  if (eff === "crashed") return "planté";
  if (suspectDead) return "mort ?";
  if (eff === "running" || eff === "orchestrating") return "en cours";
  // « provisioning » et « starting » tombaient dans le repli `String(eff)` : la description
  // accessible de la carte servait donc le mot de code brut, exactement le défaut corrigé
  // ailleurs pour « planté ». Ils disent maintenant la même chose que leur badge.
  if (eff === "provisioning") return "préparation…";
  if (eff === "starting") return "démarrage…";
  if (typeof eff === "string" && eff.startsWith("awaiting")) return "nécessite une réponse";
  if (eff === "finished") return "terminé";
  if (eff === "cli") return "terminé";
  return String(eff || "");
}
