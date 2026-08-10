// Registres DOM persistants de la sidebar + création d'une carte.
//
// Le rendu est KEYÉ : chaque `n.key` garde la MÊME instance DOM entre deux refresh.
// C'est ce qui évite les clics perdus (un nœud remplacé entre mousedown et mouseup
// n'émet aucun click) et la perte de l'état déplié.

import { node } from "../dom.js";
import { effectiveState, buildBadge } from "../badges.js";
import { openTab } from "../panel/tabs.js";
import { openRecap } from "../recap/view.js";
import { formatEventTime, formatEventTimeTooltip } from "../../time_format.js";

// --- Sidebar : racines (managers) ------------------------------------------

// --- Moteur de rendu KEYÉ (reconciliation par n.key) -----------------------
// Remplace l'ancien replaceChildren (reconstruction totale toutes les 8s) qui
// détruisait les <button.conv-item> — d'où (1) clics ratés si le re-render tombe
// entre mousedown/mouseup ("element did not become interactable") et (2) perte de
// l'état déplié (childrenBox.hidden réinitialisé). Ici chaque `key` conserve la
// MÊME instance DOM entre deux refresh : on UPDATE in-place, on n'ajoute/retire que
// le delta, on ne touche JAMAIS childrenBox.hidden en reconcile (piloté par le toggle).

// Registres persistants entre refresh (identité DOM stable).
export const groupRegistry = new Map();   // key -> rec { group,row,badgeEl,titleEl,projEl,archBtn,toggleEl,childrenBox, state,suspectDead,title,branch }
const titleRegistry = new Map();   // catKey -> <div.conv-cat-title>
let needinputWrapper = null;       // <div.conv-section-needinput> persistant
let needinputTitle = null;         // son <div.conv-cat-title> interne
export let emptyMsgEl = null;             // <p.muted> "Aucune conversation manager."
export function setEmptyMsgEl(el) { emptyMsgEl = el; }

// Crée (une fois) le DOM d'un groupe et mémorise ses slots pour update in-place.
// L'identité DOM du <button.conv-item> et de son childrenBox est ainsi préservée
// entre les refresh (fix clic raté + état déplié perdu — B3).
export function createGroup(n, depth) {
  // Ceinture + bretelles : jamais recréer un group pour une key déjà rendue
  // (le rendu keyé passe par reconcileGroups.get() avant create, mais on garde
  // cette garde idempotente à coût nul contre toute duplication de pills/rows).
  const existing = groupRegistry.get(n.key);
  if (existing) return existing;
  const group = document.createElement("div");
  group.className = "conv-group";
  const row = node(group, "button", depth > 0 ? "conv-item conv-child" : "conv-item");
  // Entrée fantôme (§3) : parent archivé synthétisé → grisée via classe dédiée.
  if (n._ghost) row.classList.add("conv-item--ghost");
  row.dataset.key = n.key;
  const rec = {
    group, row, depth,
    badgeEl: null, titleEl: null, metaEl: null, timeEl: null,
    branchWrap: null, branchNameEl: null, idBadge: null, shortId: undefined,
    archBtn: null, toggleEl: null, childrenBox: null,
    state: undefined, suspectDead: undefined, phase: undefined, title: undefined,
    branch: undefined, startedAt: undefined,
  };
  // Ordre DOM du row : [toggle?] badge title meta [archive?].
  const eff0 = effectiveState(n);
  rec.badgeEl = buildBadge(eff0, n.suspect_dead, { compact: true, phase: n.phase || "" });
  row.appendChild(rec.badgeEl);
  rec.state = eff0; rec.suspectDead = n.suspect_dead; rec.phase = n.phase || "";
  rec.titleEl = node(row, "span", "conv-item-title", n.title || n.agent_id || n.key);
  rec.title = n.title || n.agent_id || n.key;
  rec.titleEl.title = n.title_full || rec.title;
  // Heure de démarrage — formatée côté client depuis started_at (ISO UTC) via le
  // MÊME helper que les marqueurs inline → heure locale identique partout. Le
  // serveur ne cuit plus l'heure dans le titre. Tooltip = ISO complet.
  rec.timeEl = node(row, "span", "conv-item-time");
  rec.startedAt = n.started_at || "";
  rec.timeEl.textContent = formatEventTime(rec.startedAt);
  rec.timeEl.title = formatEventTimeTooltip(rec.startedAt);
  // Ligne 2 (SUJET) : premier message utilisateur / titre du ticket = n.title_full,
  // gris moyen, tronqué en 1 ligne (ellipsis CSS). Séparé du titre court (.conv-item-title)
  // que l'exigence A4 impose de garder inchangé. Créé une fois, MAJ par updateGroup.
  rec.subjectEl = node(row, "span", "conv-item-subject", n.title_full || "");
  rec.subject = n.title_full || "";
  // Entrée FLAT (sous-agent affiché en propre dans une section a/b) : lien vers le parent
  // « ↳ sous-agent de {titre} » sous le titre. n._realKey = la vraie key à ouvrir.
  if (n._realKey) {
    rec.flatParentEl = node(row, "span", "conv-flat-parent", `↳ sous-agent de ${n._flatOf || "?"}`);
  }
  // Conteneur meta (branche + id court copiable — B8) créé une fois, rempli par updateGroup.
  rec.metaEl = node(row, "span", "conv-item-meta");
  const openKey = n._realKey || n.key;
  // Pastille « Récap » (violette) DANS la ligne de l'agent — n'apparaît QUE si un récap
  // structuré existe (n.has_recap, exposé par /api/agents/tree). Clic → ouvre l'agent
  // directement sur la vue récap. stopPropagation : ne PAS déclencher l'ouverture conversation.
  rec.recapBtn = node(row, "span", "conv-recap-pill", "Récap");
  rec.recapBtn.hidden = !n.has_recap;
  rec.recapBtn.title = "Voir le récap structuré (symptômes, cause, tests, diffs)";
  rec.recapBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    openTab(openKey, n.title || n.agent_id || n.key, n.title_full);
    openRecap(openKey);
  });
  row.addEventListener("click", () => openTab(openKey, n.title || n.agent_id || n.key, n.title_full));
  groupRegistry.set(n.key, rec);
  return rec;
}
