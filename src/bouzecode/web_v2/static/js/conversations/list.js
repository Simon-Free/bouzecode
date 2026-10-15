// [desc] Liste des agents (colonne gauche) : chargement de /api/agents/tree, groupes À traiter / En cours / Terminés / Archivés avec compteurs, « Afficher plus d'agents », état vide et état d'erreur. Les cartes sont dans list_card.js, les gestes dans actions.js. [/desc]
//
// Le rafraîchissement automatique est différé tant que le pointeur est enfoncé dans la liste
// (R8) : une carte redessinée entre mousedown et mouseup ne recevrait jamais son clic.

import { api, toast, h, skeleton, failed } from "../lib/ui.js";
import { poller } from "../lib/poll.js";
import { state, emit, on } from "./store.js";
import { groupNodes, nodeState, buildTree, matchesFilter } from "./model.js";
import { reconcileCards } from "./list_card.js";
import { recallText, rememberText } from "./memory.js";

const PAGE = 40;
const ARCHIVED_OPEN_KEY = "bz.agents.archivedOpen";
const GROUPS = [
  { key: "a_traiter", label: "À traiter", tone: "warn" },
  { key: "en_cours", label: "En cours", tone: "info" },
  { key: "termines", label: "Terminés", tone: "" },
];

let listEl = null;
let treePoller = null;
let filterText = "";
let loadedLimit = PAGE;
let loadingMore = false;
let interacting = false;
let pendingRender = false;
let activeKey = null;
let openKeys = new Set();
/** Sections persistantes par groupe. */
const sections = new Map();
const archives = { open: recallText(ARCHIVED_OPEN_KEY) === "1", loading: false, loaded: false, error: null };

// ---------------------------------------------------------------- chargement

/** Numéro de la dernière lecture de l'arbre partie, et de la plus récente appliquée. */
let treeSeq = 0;
let appliedSeq = 0;

export async function refreshTree() {
  const limit = Math.max(loadedLimit, PAGE);
  const seq = ++treeSeq;
  const data = await api("GET", `/api/agents/tree?offset=0&limit=${limit}`, undefined, { timeout: 60000 });
  //  Une lecture partie AVANT une plus récente déjà appliquée (rechargement après archivage) est
  //  périmée : l'appliquer ferait réapparaître l'agent archivé jusqu'à la lecture suivante.
  if (seq < appliedSeq) return state.nodes;
  appliedSeq = seq;
  state.nodes = (data && data.nodes) || [];
  state.totalRoots = (data && data.total_roots) || 0;
  state.loaded = true;
  emit("tree", state.nodes);
  scheduleRender();
  return state.nodes;
}

async function loadMore() {
  if (loadingMore) return;
  loadingMore = true;
  loadedLimit += PAGE;
  render();
  try {
    await refreshTree();
  } catch (err) {
    loadedLimit -= PAGE;
    toast.err(`Impossible de charger la suite : ${err.message}`);
  } finally {
    loadingMore = false;
    render();
  }
}

async function loadArchived() {
  Object.assign(archives, { loading: true, error: null });
  render();
  try {
    const data = await api("GET", "/api/agents/tree?archived=1", undefined, { timeout: 60000 });
    state.archived = (data && data.nodes) || [];
    archives.loaded = true;
  } catch (err) {
    archives.error = err;
  } finally {
    archives.loading = false;
    render();
  }
}

function toggleArchived() {
  archives.open = !archives.open;
  rememberText(ARCHIVED_OPEN_KEY, archives.open ? "1" : "0");
  if (archives.open && !archives.loaded && !archives.loading) loadArchived();
  render();
}

// ---------------------------------------------------------------- sections

function groupSection(g) {
  if (!sections.has(g.key)) {
    const count = h("span", { class: "count", "data-tone": g.tone || null });
    const head = h("h2", { class: "ag-group__title" }, h("span", {}, g.label), count);
    const body = h("div", { class: "ag-group__body" });
    const el = h("section", { class: "ag-group", dataset: { group: g.key }, "aria-label": g.label }, head, body);
    sections.set(g.key, { el, body, count });
  }
  return sections.get(g.key);
}

function archivedSection() {
  if (!sections.has("archives")) {
    const toggle = h("button", { type: "button", class: "ag-group__toggle", "aria-expanded": "false" });
    toggle.addEventListener("click", toggleArchived);
    const body = h("div", { class: "ag-group__body" });
    const el = h("section", { class: "ag-group ag-group--archived", dataset: { group: "archives" } },
      h("h2", { class: "ag-group__title" }, toggle), body);
    sections.set("archives", { el, body, toggle });
  }
  return sections.get("archives");
}

function cardContext(archived) {
  return { archived, activeKey, openKeys, tree: buildTree(state.nodes) };
}

function renderGroups(groups) {
  const shown = [];
  for (const g of GROUPS) {
    const entries = groups[g.key];
    const s = groupSection(g);
    s.count.textContent = entries.length ? String(entries.length) : "";
    if (!entries.length) continue;
    reconcileCards(s.body, entries, 0, cardContext(false));
    shown.push(s.el);
  }
  return shown;
}

function emptyState() {
  const el = listEl.querySelector(":scope > .ag-list__empty") || h("div", { class: "ag-list__empty" });
  el.replaceChildren(h("div", { class: "empty" },
    h("div", { class: "empty__title" }, filterText ? `Aucun agent ne correspond à « ${filterText} »` : "Aucun agent pour l'instant"),
    h("div", { class: "empty__text" }, filterText
      ? "Appuie sur Entrée pour chercher aussi dans le contenu des conversations."
      : "Lance une conversation avec la barre en haut à droite.")));
  return el;
}

/** Bouton « Afficher plus d'agents » quand le serveur a d'autres racines ; null sinon. */
function moreButton() {
  const rootsShown = state.nodes.filter((n) => !n.parent || String(n.parent).startsWith("dispatcher:")).length;
  if (filterText || state.totalRoots <= rootsShown || state.totalRoots <= loadedLimit - 1) return null;
  let more = listEl.querySelector(":scope > .ag-list__more");
  if (!more) {
    more = h("button", { type: "button", class: "btn btn--ghost btn--sm ag-list__more" });
    more.addEventListener("click", loadMore);
  }
  more.disabled = loadingMore;
  more.setAttribute("aria-busy", loadingMore ? "true" : "false");
  more.textContent = loadingMore ? "Chargement de la suite…" : `Afficher plus d'agents (${state.totalRoots - rootsShown} de plus)`;
  return more;
}

function paintArchivedBody(body, nodes) {
  if (archives.loading) { skeleton(body, 2); return; }
  if (archives.error) { failed(body, archives.error, loadArchived, { title: "Impossible de charger les agents archivés." }); return; }
  if (!archives.loaded) return;
  if (!nodes.length) {
    body.replaceChildren(h("p", { class: "ag-muted" }, filterText ? "Aucun agent archivé ne correspond." : "Aucun agent archivé."));
    return;
  }
  for (const child of [...body.children]) if (!child.classList.contains("ag-card")) child.remove();
  reconcileCards(body, nodes.map((n) => ({ node: n, kids: [], flatKey: `${n.key}::archived` })), 0, cardContext(true));
}

function renderArchived() {
  const a = archivedSection();
  const nodes = state.archived.filter((n) => matchesFilter(n, filterText));
  a.toggle.replaceChildren(...[h("span", { "aria-hidden": "true" }, archives.open ? "▾ " : "▸ "), h("span", {}, "Archivés"),
    archives.loaded ? h("span", { class: "count" }, String(nodes.length || "")) : null].filter(Boolean));
  a.toggle.setAttribute("aria-expanded", String(archives.open));
  a.body.hidden = !archives.open;
  if (archives.open) paintArchivedBody(a.body, nodes);
  return a.el;
}

/** Place `desired` dans cet ordre sous la liste et retire le reste (sans recréer ce qui existe). */
function placeInOrder(desired) {
  let ref = listEl.firstElementChild;
  for (const el of desired) {
    if (el !== ref) listEl.insertBefore(el, ref);
    else ref = ref.nextElementSibling;
  }
  for (const child of [...listEl.children]) if (!desired.includes(child)) child.remove();
}

function scheduleRender() {
  if (interacting) { pendingRender = true; return; }
  render();
}

export function render() {
  if (!listEl || !state.loaded) return;
  listEl.removeAttribute("aria-busy");
  const visible = state.nodes.filter((n) => !state.hiding.has(n.key));
  const { groups } = groupNodes(visible, { filter: filterText });
  const desired = renderGroups(groups);
  const total = GROUPS.reduce((acc, g) => acc + groups[g.key].length, 0);
  if (!total) desired.push(emptyState());
  const more = moreButton();
  if (more) desired.push(more);
  desired.push(renderArchived());
  placeInOrder(desired);
  emit("rendered", { total });
}

// ---------------------------------------------------------------- câblage

export function setFilter(text) {
  filterText = String(text || "");
  render();
}

export function setActive(key, keys) {
  activeKey = key;
  openKeys = new Set(keys || []);
  render();
}

function isLive() {
  return state.nodes.some((n) => nodeState(n).group === "en_cours");
}

function watchPointer() {
  //  Fin du geste, quelle qu'elle soit : relâché dans la page, annulé, ou relâché HORS de la
  //  fenêtre (aucun pointerup n'arrive alors ; la fenêtre perd le focus) — sinon la liste restait
  //  figée, chaque rendu différé pour toujours.
  const endInteraction = () => {
    interacting = false;
    if (pendingRender) { pendingRender = false; render(); }
  };
  listEl.addEventListener("pointerdown", () => { interacting = true; });
  document.addEventListener("pointerup", endInteraction);
  document.addEventListener("pointercancel", endInteraction);
  window.addEventListener("blur", endInteraction);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") endInteraction(); });
}

async function pollTree() {
  try {
    await refreshTree();
  } catch (err) {
    if (!state.loaded) failed(listEl, err, () => treePoller.now(), { title: "Impossible de charger la liste des agents." });
    throw err;
  }
  return isLive();
}

export function startList() {
  listEl = document.getElementById("conv-list");
  if (!listEl) return null;
  watchPointer();
  treePoller = poller(pollTree, { interval: 15000, fastInterval: 5000, isFast: (live) => !!live });
  treePoller.start();
  if (archives.open) loadArchived();
  on("refresh-tree", () => treePoller.now());
  // Rechargement IMMÉDIAT et frais (après archivage/restauration) : jamais une lecture en vol.
  on("reload-tree", () => refreshTree());
  on("render", () => render());
  on("archives-changed", () => {
    archives.loaded = false;
    if (archives.open) loadArchived();
  });
  // Rafraîchit les « il y a N min » même sans nouvelle donnée.
  setInterval(() => { if (state.loaded) scheduleRender(); }, 60000);
  return treePoller;
}
