// État déplié/replié des cartes de la sidebar : persisté en localStorage pour
// survivre au re-render toutes les 8 s ET au rechargement de la page. Deux Sets
// distincts pour que le choix explicite de l'utilisateur prime sur l'auto-expand.

import { agentId } from "../dom.js";
import { NODES } from "../state.js";
import { CONTRACT } from "../contract.js";

// Enfants directs d'un node dans l'arbre plat (parent = agentId OU key du parent).
export function childrenOf(n) {
  const id = agentId(n.key);
  // Un node fantôme (parent archivé synthétisé) porte agent_id = l'id du parent
  // disparu ; les orphelins pointent leur parent sur cet id → on matche aussi
  // n.agent_id pour que les orphelins s'imbriquent sous le fantôme.
  const gid = n.agent_id || id;
  return NODES.filter((c) => c.parent === id || c.parent === n.key || c.parent === gid);
}

// Persistance de l'état déplié/replié entre les re-render (refreshList 8s) ET
// entre les reloads de page (localStorage). Deux Sets pour que le choix explicite
// de l'utilisateur prime sur l'auto-expand. Combinés au rendu keyé, ils garantissent
// la survie de l'état déplié même si un rec est recréé après purge/re-apparition.
const EXPANDED_LS_KEY = "bz.conv.expanded";
const COLLAPSED_LS_KEY = "bz.conv.collapsed";
function readStoredSet(lsKey) {
  try {
    const raw = localStorage.getItem(lsKey);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch (_) { return new Set(); }
}
function storeSet(lsKey, set) {
  try { localStorage.setItem(lsKey, JSON.stringify([...set])); } catch (_) {}
}
const expandedKeys = readStoredSet(EXPANDED_LS_KEY);
const collapsedKeys = readStoredSet(COLLAPSED_LS_KEY);
export function markExpanded(key) {
  expandedKeys.add(key); collapsedKeys.delete(key);
  storeSet(EXPANDED_LS_KEY, expandedKeys); storeSet(COLLAPSED_LS_KEY, collapsedKeys);
}
export function markCollapsed(key) {
  collapsedKeys.add(key); expandedKeys.delete(key);
  storeSet(EXPANDED_LS_KEY, expandedKeys); storeSet(COLLAPSED_LS_KEY, collapsedKeys);
}
export function forgetToggle(key) {
  expandedKeys.delete(key); collapsedKeys.delete(key);
  storeSet(EXPANDED_LS_KEY, expandedKeys); storeSet(COLLAPSED_LS_KEY, collapsedKeys);
}

// Calcule l'état ouvert désiré pour un node donné (choix user > auto-expand).
// Auto-ouverture UNIQUEMENT si un enfant est awaiting_* (needsInput). Un enfant
// running seul ne déplie PAS (spec T1 : « déplié à la demande »).
export function desiredOpen(n, kids) {
  const autoExpand = kids.some((k) => CONTRACT.needsInput(k));
  return collapsedKeys.has(n.key) ? false : (expandedKeys.has(n.key) || autoExpand);
}

// Agrège les états des enfants pour le libellé du header de repli.
// Ex. "2 sous-agents · 1 en cours". running -> "en cours", awaiting_* -> "en attente".
export function aggregateChildren(kids) {
  const n = kids.length;
  const running = kids.filter((k) => k.state === "running").length;
  const awaiting = kids.filter((k) => CONTRACT.needsInput(k)).length;
  const parts = [`${n} sous-agent${n > 1 ? "s" : ""}`];
  if (awaiting) parts.push(`${awaiting} en attente`);
  if (running) parts.push(`${running} en cours`);
  return parts.join(" · ");
}
