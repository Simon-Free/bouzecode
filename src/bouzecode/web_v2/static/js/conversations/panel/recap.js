// [desc] Vue Récap du panneau d'un agent : récap structuré (symptômes, cause, tests, modifications) et diffs, récap consolidé des sous-agents ; rechargée quand l'agent en produit un nouveau (recap_version). Squelette, erreur avec Réessayer, état vide. [/desc]

import { api, h, skeleton, failed, empty } from "../../lib/ui.js";
import { emit } from "../store.js";
import { canonicalKey } from "../model.js";
import { renderDiffBlock } from "./diff.js";
import { refreshButton } from "./view_tools.js";
import { fichiersLivres } from "../../lib/fichiers_livres.js";

const DIFF_SECTIONS = { changes: "Modifications", other: "Autres modifications", tests: "Tests", all: "Diffs" };
const TEXT_SECTIONS = [["Symptômes", "symptoms"], ["Cause / plan", "explanation"], ["Tests", "tests"]];

function changeItem(c) {
  return h("li", {}, h("code", {}, (c && c.file) || ""), c && c.summary ? ` — ${c.summary}` : "");
}

function recapText(root, recap) {
  for (const [label, field] of TEXT_SECTIONS) {
    if (!recap[field]) continue;
    root.appendChild(h("section", { class: "ag-recap__section" }, h("h3", {}, label), h("div", { class: "ag-recap__body" }, String(recap[field]))));
  }
  const changes = Array.isArray(recap.changes) ? recap.changes : [];
  if (!changes.length) return;
  root.appendChild(h("section", { class: "ag-recap__section" }, h("h3", {}, "Modifications"),
    h("ol", { class: "ag-recap__changes" }, ...changes.map(changeItem))));
}

function recapDiffs(root, diffs) {
  let current = null;
  for (const d of diffs || []) {
    if (d.section !== current) {
      current = d.section;
      root.appendChild(h("h3", { class: "ag-recap__diffs-title" }, DIFF_SECTIONS[current] || "Diffs"));
    }
    renderDiffBlock(root, d);
  }
}

function childCard(child) {
  const open = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, "Ouvrir");
  open.addEventListener("click", () => emit("open", { key: canonicalKey(child.agent_id), title: child.title }));
  const card = h("article", { class: "card ag-recap__child" },
    h("div", { class: "card__head" }, h("h3", { class: "card__title" }, child.title || child.agent_id), open));
  if (!child.recap) {
    card.appendChild(h("p", { class: "ag-muted" }, "Pas de récap pour ce sous-agent : ouvre sa conversation."));
    return card;
  }
  recapText(card, child.recap);
  recapDiffs(card, child.diffs);
  return card;
}

function renderAggregate(root, children) {
  if (!children.length) { empty(root, { title: "Aucun récap de sous-agent pour ce lot." }); return; }
  root.appendChild(h("p", { class: "ag-muted" }, `Récap consolidé de ${children.length} sous-agent(s) :`));
  for (const child of children) root.appendChild(childCard(child));
}

function renderSingle(root, payload) {
  const recap = payload.recap;
  if (!recap || payload.recap_missing) {
    root.appendChild(h("div", { class: "empty empty--inline" },
      h("div", { class: "empty__title" }, "Pas encore de récap structuré."),
      h("div", { class: "empty__text" }, "L'agent en produit un en rendant sa réponse finale. Les diffs disponibles sont affichés ci-dessous.")));
  } else {
    recapText(root, recap);
  }
  const fichiers = fichiersLivres(payload.related_files, { session_id: payload.session_key });
  if (fichiers) root.appendChild(fichiers);
  if ((payload.diffs || []).length) recapDiffs(root, payload.diffs);
  else if (recap) root.appendChild(h("p", { class: "ag-muted" }, "Aucun diff enregistré pour cette session."));
}

function renderRecap(root, payload) {
  root.replaceChildren();
  if (payload && payload.is_aggregate && Array.isArray(payload.children)) renderAggregate(root, payload.children);
  else renderSingle(root, payload || {});
}

function showLoadError(body, err, retry) {
  if (err.status === 404 && err.code === "session_introuvable") {
    empty(body, { title: "Cette conversation n'existe plus.", text: "Impossible d'afficher son récap." });
  } else {
    failed(body, err, retry, { title: "Impossible de charger le récap." });
  }
}

export function createRecapView(entry, pane) {
  const tools = h("div", { class: "ag-view__tools" });
  const body = h("div", { class: "ag-view__body ag-recap" });
  pane.append(tools, body);
  let version = null; // signature du récap affiché (null : rien d'affiché)
  let loading = false;

  /** mode "full" : squelette puis rendu ; "check" : ne redessine que si le récap a changé. */
  async function load(mode) {
    if (loading) return;
    loading = true;
    //  `version` : null tant que rien n'est affiché, sinon la SIGNATURE du contenu affiché. Ni
    //  `recap_version` brut (absent sans récap structuré : comparé à "", tout était redessiné,
    //  squelette compris, à chaque vérification), ni lui seul (c'est le mtime de la session, qui
    //  bouge à chaque tour) : diffs refermés et lecture remise en haut toutes les 1,5 s.
    if (version === null || mode === "full") skeleton(body, 5);
    try {
      const data = await api("GET", `/api/sessions/${entry.key}/recap`, undefined, { timeout: 30000 });
      const nouvelle = JSON.stringify({ ...data, recap_version: null });
      if (mode !== "check" || nouvelle !== version) renderRecap(body, { ...data, session_key: entry.key });
      body.removeAttribute("aria-busy");
      version = nouvelle;
      tools.replaceChildren(h("span", { class: "ag-muted" }, data.recap_missing ? "" : "Récap à jour."), refreshButton("Actualiser", () => load("full")));
    } catch (err) {
      showLoadError(body, err, () => load("full"));
      version = null;
    } finally {
      loading = false;
    }
  }
  return {
    show() { load(version !== null ? "check" : "full"); },
    maybeRefresh() { if (version !== null) load("check"); },
  };
}
