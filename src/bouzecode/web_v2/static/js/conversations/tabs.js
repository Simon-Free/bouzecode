// [desc] Onglets d'agents ouverts : barre d'onglets (état + pastille « nouveau »), ouverture / activation / fermeture au clavier, rebranchement d'un onglet de lancement vers le vrai agent, mémorisation des onglets et lien profond `?agent=`. [/desc]

import { h } from "../lib/ui.js";
import { badge } from "../lib/states.js";
import { emit, on, findNode } from "./store.js";
import { canonicalKey, nodeState, titleFromPrompt } from "./model.js";
import { createPanel } from "./panel/panel.js";
import { recallJson, rememberJson } from "./memory.js";

const TABS_KEY = "bz.agents.tabs";
/** key → entry */
export const tabs = new Map();
let activeKey = null;
let tabsBar = null;
let panelsEl = null;
let emptyEl = null;

function persist() {
  rememberJson(TABS_KEY, { keys: [...tabs.keys()].filter((k) => k.startsWith("agent/")), active: activeKey });
}

function syncUrl() {
  try {
    const url = new URL(location.href);
    if (activeKey && activeKey.startsWith("agent/")) url.searchParams.set("agent", activeKey.slice(6));
    else url.searchParams.delete("agent");
    history.replaceState(null, "", url.toString());
  } catch (err) { console.warn("URL non mise à jour", err); }
}

function publish() {
  emit("tabs", { active: activeKey, keys: [...tabs.keys()] });
  persist();
  syncUrl();
  if (emptyEl) emptyEl.hidden = tabs.size > 0;
}

export function activeEntry() {
  return activeKey ? tabs.get(activeKey) : null;
}

/** Met à jour l'onglet (icône d'état, titre, pastille « nouveau »). */
export function paintTab(entry) {
  const st = entry.stateInfo || nodeState(findNode(entry.key) || { etat: entry.key.startsWith("launching/") ? "preparing" : "" });
  const sig = `${st.key}|${entry.title}|${entry.unread ? 1 : 0}|${activeKey === entry.key}`;
  if (entry.tabSig === sig) return;
  entry.tabSig = sig;
  //  Onglet : l'icône d'état seule (le libellé reste lu par les lecteurs d'écran et en infobulle).
  const b = badge(st, { compact: true, text: true });
  b.classList.add("ag-tab__state");
  entry.tabLabel.replaceChildren(b, h("span", { class: "ag-tab__title" }, entry.title || "Agent"));
  entry.tabEl.title = `${entry.title} — ${st.label}`;
  entry.tabEl.classList.toggle("has-unread", !!entry.unread);
  entry.tabDot.hidden = !entry.unread;
}

export function activate(key) {
  const entry = tabs.get(key);
  if (!entry) return;
  activeKey = key;
  for (const [k, e] of tabs) {
    const on_ = k === key;
    e.tabEl.setAttribute("aria-selected", String(on_));
    e.tabEl.tabIndex = on_ ? 0 : -1;
    e.panelEl.hidden = !on_;
    if (on_) { e.unread = false; }
    e.setActive(on_);
    paintTab(e);
  }
  publish();
}

export function closeTab(key) {
  const entry = tabs.get(key);
  if (!entry) return;
  entry.destroy();
  entry.tabEl.remove();
  entry.panelEl.remove();
  const order = [...tabs.keys()];
  const idx = order.indexOf(key);
  tabs.delete(key);
  if (activeKey === key) {
    activeKey = null;
    const next = order[idx + 1] || order[idx - 1];
    if (next && tabs.has(next)) activate(next);
  }
  publish();
  const nextEntry = activeEntry();
  if (nextEntry) nextEntry.tabEl.focus();
}

/**
 * Ouvre (ou active) l'onglet d'un agent.
 * @param {{key:string, title?:string, prompt?:string, launch?:object, focus?:boolean}} o
 *   launch : {prompt, project_slug, typology, isolation} pour pouvoir RÉESSAYER un lancement.
 */
/** Téléphone : la liste est AU-DESSUS du panneau ; un agent ouvert à la main amène le panneau à l'écran. */
function revealPanel(o) {
  if (o.focus === false || !window.matchMedia || !window.matchMedia("(max-width: 860px)").matches) return;
  const main = panelsEl && panelsEl.closest(".ag-main");
  if (main && typeof main.scrollIntoView === "function") main.scrollIntoView({ block: "start" });
}

export function openTab(o) {
  const key = canonicalKey(o.key);
  if (!key) return null;
  if (tabs.has(key)) { activate(key); revealPanel(o); return tabs.get(key); }
  const node = findNode(key);
  const title = o.title || (node && (node.title || node.tache_titre)) || titleFromPrompt(o.prompt) || key.split("/")[1].slice(0, 8);

  const tabLabel = h("span", { class: "ag-tab__label" });
  const tabDot = h("span", { class: "ag-tab__dot", "aria-label": "nouveau contenu", hidden: true });
  const close = h("button", { type: "button", class: "ag-tab__close", "aria-label": `Fermer l'onglet « ${title} »`, tabindex: "-1" }, "×");
  const tabEl = h("div", { class: "ag-tab", role: "tab", "aria-selected": "false", tabindex: "-1" }, tabLabel, tabDot, close);
  tabsBar.appendChild(tabEl);
  const panelEl = h("div", { class: "ag-panel", role: "tabpanel", hidden: true });
  panelsEl.appendChild(panelEl);

  const entry = { key, title, tabEl, tabLabel, tabDot, panelEl, unread: false, launch: o.launch || null, tabSig: "" };
  tabs.set(key, entry);
  Object.assign(entry, createPanel(entry, {
    retarget: (newKey, newTitle) => retarget(entry, newKey, newTitle),
    repaintTab: () => paintTab(entry),
    close: () => closeTab(entry.key),
  }));

  tabEl.addEventListener("click", (e) => { if (!close.contains(e.target)) activate(entry.key); });
  close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(entry.key); });
  tabEl.addEventListener("keydown", (e) => onTabKey(entry, e));
  paintTab(entry);
  activate(key);
  if (o.focus !== false) tabEl.focus({ preventScroll: true });
  revealPanel(o);
  return entry;
}

/** Clavier sur un onglet : flèches pour passer d'un onglet à l'autre, Suppr / Ctrl+W pour fermer, Entrée pour activer. */
function onTabKey(entry, e) {
  const keys = [...tabs.keys()];
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault();
    const step = e.key === "ArrowRight" ? 1 : -1;
    const next = keys[(keys.indexOf(entry.key) + step + keys.length) % keys.length];
    activate(next);
    tabs.get(next).tabEl.focus();
  } else if (e.key === "Delete" || (e.key === "w" && (e.ctrlKey || e.metaKey))) {
    e.preventDefault();
    closeTab(entry.key);
  } else if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    activate(entry.key);
  }
}

/** Rebranche un onglet (clé provisoire `launching/<t>`) sur la vraie clé `agent/<id>`. */
function retarget(entry, newKey, newTitle) {
  const oldKey = entry.key;
  if (oldKey === newKey) return;
  if (tabs.has(newKey)) {
    // L'agent est déjà ouvert ailleurs : on ferme le provisoire et on active le vrai.
    closeTab(oldKey);
    activate(newKey);
    return;
  }
  // Même position dans la barre : on reconstruit la table en gardant l'ordre.
  const ordered = [...tabs];
  tabs.clear();
  for (const [k, e] of ordered) tabs.set(k === oldKey ? newKey : k, e);
  entry.key = newKey;
  if (newTitle) entry.title = newTitle;
  if (activeKey === oldKey) activeKey = newKey;
  entry.tabSig = "";
  paintTab(entry);
  publish();
}

export function initTabs() {
  tabsBar = document.getElementById("conv-tabs");
  panelsEl = document.getElementById("conv-panels");
  emptyEl = panelsEl && panelsEl.querySelector(".conv-empty");
  on("open", (o) => openTab({ key: o.key, title: o.title || (o.node && o.node.title), launch: o.launch }));
  on("tree", () => {
    for (const e of [...tabs.values()]) { if (e.onTree) e.onTree(); paintTab(e); }
  });
}

/** Rouvre les onglets de la dernière visite, puis l'agent du lien profond `?agent=`. */
export function restoreTabs() {
  const saved = recallJson(TABS_KEY, null) || { keys: [], active: null };
  const params = new URLSearchParams(location.search);
  const deep = params.get("agent");
  for (const k of (saved.keys || []).slice(0, 8)) openTab({ key: k, focus: false });
  if (deep) openTab({ key: deep, focus: false });
  else if (saved.active && tabs.has(saved.active)) activate(saved.active);
}
