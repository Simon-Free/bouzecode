// [desc] Profils : colonne de gauche — « Mes profils » (éditables) et « Fournis » (lecture seule), filtre, sélection. [/desc]
import { h, empty } from "../lib/ui.js";
import { S } from "./state.js";

const $ = (id) => document.getElementById(id);
let onPick = () => {};

/** `cb(name)` est appelé quand l'utilisateur choisit un profil dans la liste. */
export function onSelect(cb) { onPick = cb; }

function item(a) {
  const selected = S.current.mode !== "new" && S.current.name === a.name;
  const missing = (a.missing && (a.missing.tools.length + a.missing.skills.length)) || 0;
  const btn = h("button", {
    type: "button", class: "pf-item", "data-name": a.name,
    "aria-current": selected ? "true" : null,
    title: a.editable ? a.name : `${a.name} — profil fourni (${a.source}), lecture seule`,
  },
  h("span", { class: "pf-item__name" }, a.editable ? "" : h("span", { "aria-hidden": "true", class: "pf-item__lock" }, "🔒 "), a.name,
    missing ? h("span", { class: "pf-tag pf-tag--warn", title: `${missing} outil(s) ou skill(s) introuvable(s)` }, "!") : null),
  h("span", { class: "pf-item__desc" }, a.description || (a.editable ? "Sans description" : `${a.kind} · ${a.source}`)));
  btn.addEventListener("click", () => onPick(a.name));
  return btn;
}

/** Redessine la liste depuis S.agents (filtre et sélection compris). */
export function renderList() {
  const box = $("pf-list");
  const q = $("pf-filter").value.trim().toLowerCase();
  const match = (a) => !q || a.name.toLowerCase().includes(q) || (a.description || "").toLowerCase().includes(q);
  const mine = S.agents.filter((a) => a.editable).filter(match);
  const provided = S.agents.filter((a) => !a.editable).filter(match);
  const parts = [];
  parts.push(h("h2", { class: "pf-list__group" }, `Mes profils (${mine.length})`));
  if (mine.length) parts.push(...mine.map(item));
  else parts.push(h("p", { class: "pf-muted pf-list__empty" }, q ? "Aucun de tes profils ne correspond." : "Aucun profil à toi pour l'instant : crée-en un ou duplique un profil fourni."));
  parts.push(h("h2", { class: "pf-list__group" }, `Fournis (${provided.length})`));
  if (provided.length) parts.push(...provided.map(item));
  else if (q) parts.push(h("p", { class: "pf-muted pf-list__empty" }, "Aucun profil fourni ne correspond."));
  if (q && !mine.length && !provided.length) {
    empty(box, { title: `Aucun profil ne correspond à « ${q} ».`, inline: true });
    return;
  }
  box.removeAttribute("aria-busy");
  box.replaceChildren(...parts);
}

/** L'élément de liste d'un profil (pour le surligner après enregistrement). */
export function itemOf(name) {
  return $("pf-list").querySelector(`.pf-item[data-name="${CSS.escape(name)}"]`);
}

export function wireList() {
  $("pf-filter").addEventListener("input", renderList);
  $("pf-filter").addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("pf-filter").value) { $("pf-filter").value = ""; renderList(); }
  });
}
