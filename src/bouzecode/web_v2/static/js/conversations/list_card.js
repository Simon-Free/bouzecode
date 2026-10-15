// [desc] Carte d'un agent dans la liste : titre, puis UNE ligne (état en texte + activité/question/tâche), le reste au survol ; menu ⋯, sous-agents repliables ; rendu KEYÉ (la même carte garde le même élément DOM d'un rafraîchissement à l'autre). [/desc]
//
// Un élément remplacé entre mousedown et mouseup ne reçoit jamais son clic : d'où le rendu
// keyé, et le repeint limité aux cartes dont la signature a changé.

import { menu, relTime, h } from "../lib/ui.js";
import { badge } from "../lib/states.js";
import { formatEventTimeTooltip } from "../time_format.js";
import { state, emit } from "./store.js";
import { nodeState, agentIdOf, childrenSummary, isAwaitingUser } from "./model.js";
import { archiveNode, restoreKeys, copyText, openTaskOnBureau } from "./actions.js";
import { recallJson, rememberJson } from "./memory.js";

const EXPANDED_KEY = "bz.agents.expanded";
const COLLAPSED_KEY = "bz.agents.collapsed";
const MAX_DEPTH = 4;
const STALE_HINT = "Aucun signe de vie depuis plus de 4 minutes : outil long, ou agent bloqué.";

const expanded = new Set(recallJson(EXPANDED_KEY, []));
// Le choix explicite de l'utilisateur (replier) prime sur l'ouverture automatique.
const collapsed = new Set(recallJson(COLLAPSED_KEY, []));
/** flatKey → élément de carte. */
const cards = new Map();

function isAgentKey(key) { return String(key).startsWith("agent/"); }

function menuItems(node, archived) {
  const items = [{ label: "Ouvrir", fn: () => emit("open", { key: node.key, node }) }];
  if (isAgentKey(node.key)) {
    items.push({ label: "Copier l'identifiant", fn: () => copyText(node.agent_id || agentIdOf(node.key), "Identifiant") });
  }
  if (node.micro_id) items.push({ label: "Voir la tâche sur le Bureau", fn: () => openTaskOnBureau(node.micro_id) });
  items.push("sep");
  if (archived) items.push({ label: "Restaurer", fn: () => restoreKeys([node.key], node.title) });
  else if (isAgentKey(node.key)) items.push({ label: "Archiver", fn: () => archiveNode(node) });
  return items;
}

/** Ce qui ne s'affiche qu'au survol : tout le contexte, pour garder la carte sur deux lignes. */
function hoverDetails(node, entry, st) {
  const time = node.saved_at || node.started_at || "";
  const repo = node.project_name || node.project_slug;
  const lines = [
    [true, cardTitle(node)], [true, st.label],
    [time, () => `${relTime(time)} (${formatEventTimeTooltip(time)})`],
    [entry.parentTitle, () => `sous-agent de « ${entry.parentTitle} »`],
    [node.tache_titre, () => `tâche : ${node.tache_titre}`],
    [repo, () => `dépôt : ${repo}`],
    [node.branch, () => `branche : ${node.branch}`],
    [node.agent_id, () => `#${node.agent_id}`],
  ];
  return lines.filter(([ok]) => ok).map(([, v]) => (typeof v === "function" ? v() : v)).join("\n");
}

function runningActivity(node) {
  const phrase = node.activity_label || node.phase_label || "";
  return phrase && node.phase_detail ? `${phrase} — ${node.phase_detail}` : phrase;
}

/** LA ligne secondaire : erreur de lancement, question, activité, sinon tâche liée ou parent. */
function detailLine(node, entry, st) {
  if (st.key === "launch_failed") return node.launch_error || "Le lancement a échoué.";
  if (isAwaitingUser(st) && node.question) return `« ${node.question} »`;
  if (st.group === "en_cours" && runningActivity(node)) return runningActivity(node);
  if (entry.parentTitle) return `↳ ${entry.parentTitle}`;
  return node.tache_titre && node.tache_titre !== node.title ? node.tache_titre : "";
}

function signature(node, entry, extra) {
  return JSON.stringify([node.etat, node.state, node.phase, node.title, node.tache_titre, node.project_name,
    node.activity_label, node.phase_label, node.phase_detail, node.stale, node.question, node.launch_error,
    node.saved_at, node.started_at, node.branch, entry.parentTitle, extra, Math.floor(Date.now() / 60000)]);
}

function buildCard(node) {
  const el = h("div", { class: "ag-card", dataset: { key: node.key } });
  const main = h("button", { type: "button", class: "ag-card__main" });
  main.addEventListener("click", () => emit("open", { key: el._node.key, node: el._node }));
  const more = h("button", { type: "button", class: "btn btn--ghost btn--sm btn--icon ag-card__more",
    "aria-label": `Actions pour « ${node.title || "cet agent"} »` }, "⋯");
  // `menu()` s'accroche à l'élément en place : le bouton doit déjà avoir son parent.
  el.append(h("div", { class: "ag-card__row" }, main, h("span", { class: "menu" }, more)));
  menu(more, () => menuItems(el._node, el._archived));
  el._main = main;
  return el;
}

function cardTitle(node) {
  return node.title || node.tache_titre || node.agent_id || node.key;
}

function paintMain(el, node, entry, st) {
  const title = cardTitle(node);
  const detail = detailLine(node, entry, st);
  el.dataset.tone = st.tone;
  const line = h("span", { class: "ag-card__line" }, badge(st, { text: true }));
  if (detail) {
    line.append(h("span", { class: `ag-card__detail${node.stale ? " is-stale" : ""}`,
      title: node.stale ? STALE_HINT : "" }, detail));
  }
  el._main.replaceChildren(h("span", { class: "ag-card__title" }, title), line);
  el._main.setAttribute("aria-label", `${title} — ${st.label}${detail ? ` — ${detail}` : ""}`);
  el._main.title = hoverDetails(node, entry, st);
}

function toggleKids(key, open) {
  (open ? expanded : collapsed).add(key);
  (open ? collapsed : expanded).delete(key);
  rememberJson(EXPANDED_KEY, [...expanded]);
  rememberJson(COLLAPSED_KEY, [...collapsed]);
  emit("render");
}

function isKidsOpen(node, kids) {
  if (collapsed.has(node.key)) return false;
  return expanded.has(node.key) || kids.some((k) => isAwaitingUser(nodeState(k)));
}

function removeKids(el) {
  if (!el._kidsToggle) return;
  el._kidsToggle.remove(); el._kidsBox.remove();
  el._kidsToggle = null; el._kidsBox = null;
}

function paintKids(el, entry, depth, ctx) {
  const node = entry.node;
  const kids = entry.kids || [];
  if (!kids.length || depth >= MAX_DEPTH) { removeKids(el); return; }
  if (!el._kidsToggle) {
    el._kidsToggle = h("button", { type: "button", class: "ag-card__kids-toggle" });
    el._kidsBox = h("div", { class: "ag-card__kids" });
    el._kidsToggle.addEventListener("click", () => toggleKids(el._node.key, el._kidsBox.hidden));
    el.append(el._kidsToggle, el._kidsBox);
  }
  const open = isKidsOpen(node, kids);
  el._kidsToggle.textContent = `${open ? "▾" : "▸"} ${childrenSummary(kids)}`;
  el._kidsToggle.setAttribute("aria-expanded", String(open));
  el._kidsBox.hidden = !open;
  if (!open) return;
  const entries = kids.filter((k) => !state.hiding.has(k.key)).map((k) => ({
    node: k, kids: ctx.tree.children.get(k.agent_id || agentIdOf(k.key)) || [], flatKey: `${k.key}::in:${node.key}` }));
  reconcileCards(el._kidsBox, entries, depth + 1, ctx);
}

function paintCard(el, entry, depth, ctx) {
  const node = entry.node;
  const isActive = ctx.activeKey === node.key;
  const isOpenTab = ctx.openKeys.has(node.key);
  el._node = node;
  el._archived = ctx.archived;
  el.classList.toggle("is-active", isActive);
  el.classList.toggle("is-open", isOpenTab);
  el.classList.toggle("is-hiding", state.hiding.has(node.key));
  el.dataset.depth = String(depth);
  const sig = signature(node, entry, [isActive, isOpenTab, ctx.archived]);
  if (el._sig !== sig) {
    el._sig = sig;
    paintMain(el, node, entry, ctx.archived ? nodeState({ ...node, etat: "archived" }) : nodeState(node));
  }
  paintKids(el, entry, depth, ctx);
}

function dropStaleCards(container, want) {
  for (const child of [...container.children]) {
    if (!child.classList.contains("ag-card")) continue;
    const found = [...cards.entries()].find(([, v]) => v === child);
    if (found && want.has(found[0])) continue;
    if (found) cards.delete(found[0]);
    child.remove();
  }
}

/**
 * Place dans `container`, dans l'ordre, une carte par entrée ({node, kids, flatKey, parentTitle?}).
 * @param {{archived:boolean, activeKey:string|null, openKeys:Set<string>, tree:object}} ctx
 */
export function reconcileCards(container, entries, depth, ctx) {
  let ref = container.firstElementChild;
  for (const entry of entries) {
    let el = cards.get(entry.flatKey);
    if (!el) { el = buildCard(entry.node); cards.set(entry.flatKey, el); }
    paintCard(el, entry, depth, ctx);
    if (el !== ref) container.insertBefore(el, ref);
    else ref = ref.nextElementSibling;
  }
  dropStaleCards(container, new Set(entries.map((e) => e.flatKey)));
}
