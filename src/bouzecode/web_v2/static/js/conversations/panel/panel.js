// [desc] Panneau d'un agent : en-tête (état, actions), onglets de vue Fil / Récap / Fichiers modifiés / Coûts & tours, et câblage du fil, de la question et du champ de message. [/desc]

import { h } from "../../lib/ui.js";
import { createHeader } from "./header.js";
import { createThread } from "./thread.js";
import { createRecapView } from "./recap.js";
import { createFilesView } from "./files.js";
import { createCostsView } from "./costs.js";

const VIEWS = [
  { key: "fil", label: "Fil" },
  { key: "recap", label: "Récap" },
  { key: "files", label: "Fichiers modifiés" },
  { key: "costs", label: "Coûts & tours" },
];

/** Barre d'onglets de vue + un volet par vue ; `onSelect(view)` au clic et aux flèches. */
function createViewBar(panelEl, onSelect) {
  const bar = h("div", { class: "tabs ag-views", role: "tablist", "aria-label": "Vues de l'agent" });
  const buttons = {};
  const panes = {};
  panelEl.appendChild(bar);
  for (const v of VIEWS) {
    buttons[v.key] = h("button", { type: "button", class: "tab", role: "tab", "aria-selected": v.key === "fil" ? "true" : "false", dataset: { view: v.key } }, v.label);
    bar.appendChild(buttons[v.key]);
    panes[v.key] = h("div", { class: `ag-pane ag-pane--${v.key}`, role: "tabpanel", hidden: v.key !== "fil" });
    panelEl.appendChild(panes[v.key]);
  }
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]");
    if (b) onSelect(b.dataset.view);
  });
  bar.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const order = VIEWS.map((v) => v.key).filter((k) => !buttons[k].disabled);
    const current = order.indexOf(bar.querySelector("[aria-selected=true]").dataset.view);
    const next = order[(current + (e.key === "ArrowRight" ? 1 : -1) + order.length) % order.length];
    e.preventDefault();
    onSelect(next);
    buttons[next].focus();
  });
  return { buttons, panes };
}

/**
 * Construit le contenu de `entry.panelEl` et renvoie les méthodes que tabs.js appelle :
 * `setActive(bool)`, `destroy()`, `onTree()`.
 */
export function createPanel(entry, hooks) {
  const headEl = h("header", { class: "ag-head" });
  entry.panelEl.appendChild(headEl);
  const { buttons, panes } = createViewBar(entry.panelEl, (view) => setView(view));
  entry.view = "fil";
  entry.active = false;

  const header = createHeader(entry, headEl, hooks);
  const thread = createThread(entry, panes.fil, {
    ...hooks,
    onStatus: () => { header.update(); updateViews(); },
    onUnread: () => { if (!entry.active) { entry.unread = true; hooks.repaintTab(); } },
  });
  entry.thread = thread;
  const views = { recap: createRecapView(entry, panes.recap), files: createFilesView(entry, panes.files), costs: createCostsView(entry, panes.costs) };

  /** Les vues secondaires n'existent que pour un agent né (pas pendant son lancement). */
  function updateViews() {
    const agent = entry.key.startsWith("agent/");
    for (const key of Object.keys(views)) {
      buttons[key].disabled = !agent;
      buttons[key].title = agent ? "" : "Disponible une fois l'agent démarré.";
    }
    if (views[entry.view]) views[entry.view].maybeRefresh();
  }

  function setView(view) {
    if (buttons[view].disabled) return;
    entry.view = view;
    for (const v of VIEWS) {
      buttons[v.key].setAttribute("aria-selected", String(v.key === view));
      panes[v.key].hidden = v.key !== view;
    }
    if (views[view]) views[view].show();
    if (view === "fil") thread.onShown();
  }
  entry.setView = setView;

  header.update();
  updateViews();
  thread.start();

  return {
    setActive(on) {
      entry.active = on;
      thread.setActive(on);
    },
    destroy() { thread.stop(); },
    onTree() {
      thread.onTree();
      header.update();
      updateViews();
    },
  };
}
