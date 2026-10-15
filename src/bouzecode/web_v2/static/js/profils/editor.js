// [desc] Profils : l'éditeur (nom, description, capacités par préréglage, instructions, garde-fous, modèle ; skills dans skills_chips.js), sa collecte et son suivi « modifié ». [/desc]
import { h } from "../lib/ui.js";
import {
  S, PRESETS, presetTools, presetOf, selectableTools, toolsOfProfile,
} from "./state.js";
import { getSkills, setSkills, renderSkillChips, wireSkillSearch } from "./skills_chips.js";

const $ = (id) => document.getElementById(id);

// Sélection courante (source de vérité ; le DOM en est le reflet).
let tools = new Set();
let baseline = "";
let onEditCb = () => {};

/** Branche le rappel appelé à CHAQUE modification (aperçu, indicateur « modifié »). */
export function onEdit(cb) { onEditCb = cb; }

function edited() { onEditCb(); }

// ---------------------------------------------------------------- capacités

function renderPresets() {
  const box = $("pf-presets");
  const current = presetOf([...tools].filter((n) => isKnownTool(n)), S.catalog);
  box.replaceChildren(...PRESETS.map((p) => {
    const b = h("button", {
      type: "button", class: "seg__btn", role: "radio", "data-preset": p.key, title: p.hint,
      "aria-checked": String(p.key === current), "aria-pressed": String(p.key === current),
    }, p.label);
    b.addEventListener("click", () => choosePreset(p.key));
    return b;
  }));
  const n = [...tools].length;
  const missing = [...tools].filter((t) => !isKnownTool(t)).length;
  $("pf-caps-summary").textContent = `${n} outil${n > 1 ? "s" : ""} actif${n > 1 ? "s" : ""}`
    + " + outils système (méthodologie, extraits, réponse finale)"
    + (missing ? ` · ${missing} introuvable${missing > 1 ? "s" : ""}` : "");
}

function isKnownTool(name) {
  return (S.catalog.tools || []).some((t) => t.name === name);
}

function choosePreset(key) {
  if (key === "perso") { openTools(true); return; }
  const names = presetTools(key, S.catalog);
  // Les outils introuvables restent sélectionnés : un préréglage ne les efface pas en silence.
  const missing = [...tools].filter((t) => !isKnownTool(t));
  tools = new Set([...names, ...missing]);
  renderTools();
  renderPresets();
  edited();
}

function openTools(open) {
  const panel = $("pf-tools-panel");
  panel.hidden = !open;
  $("pf-customize").setAttribute("aria-expanded", String(open));
  $("pf-customize").textContent = open ? "Masquer la liste des outils" : "Personnaliser les outils";
  if (open) $("pf-tools-filter").focus();
}

function toolRow(name, desc, { readOnly = false, missing = false } = {}) {
  const cb = h("input", { type: "checkbox", value: name });
  cb.checked = tools.has(name);
  cb.addEventListener("change", () => {
    if (cb.checked) tools.add(name); else tools.delete(name);
    renderPresets();
    edited();
  });
  const label = h("label", { class: `pf-check${missing ? " pf-check--missing" : ""}`, "data-search": `${name} ${desc || ""}`.toLowerCase() },
    cb,
    h("span", { class: "pf-check__body" },
      h("span", { class: "pf-check__name" }, name,
        readOnly ? h("span", { class: "pf-tag" }, "lecture") : null,
        missing ? h("span", { class: "pf-tag pf-tag--warn", title: "Absent du catalogue actuel (plugin retiré ?). Conservé tant que tu ne le décoches pas." }, "introuvable") : null),
      desc ? h("span", { class: "pf-check__desc" }, desc) : null));
  return label;
}

function renderTools() {
  const box = $("pf-tools");
  const rows = selectableTools(S.catalog).map((t) => toolRow(t.name, t.description, { readOnly: t.read_only }));
  const missing = [...tools].filter((t) => !isKnownTool(t)).map((n) => toolRow(n, "", { missing: true }));
  box.replaceChildren(...missing, ...rows);
  applyToolFilter();
}

function applyToolFilter() {
  const q = $("pf-tools-filter").value.trim().toLowerCase();
  let shown = 0;
  for (const el of $("pf-tools").querySelectorAll(".pf-check")) {
    const ok = !q || el.dataset.search.includes(q);
    el.hidden = !ok;
    if (ok) shown++;
  }
  let none = $("pf-tools").querySelector(".pf-none");
  if (!shown) {
    if (!none) $("pf-tools").appendChild(h("p", { class: "pf-none pf-muted" }, `Aucun outil ne correspond à « ${q} ».`));
  } else if (none) none.remove();
}

// ---------------------------------------------------------------- garde-fous & modèle

function renderHooks() {
  const box = $("pf-hooks");
  box.replaceChildren(...(S.catalog.hooks || []).map((hk) => {
    const def = hk.default === false ? "désactivé" : "activé";
    const sel = h("select", { class: "select", id: `pf-hook-${hk.name}`, "data-hook": hk.name },
      h("option", { value: "" }, `Par défaut (${def})`),
      h("option", { value: "on" }, "Activé"),
      h("option", { value: "off" }, "Désactivé"));
    sel.addEventListener("change", edited);
    return h("div", { class: "field pf-hook" },
      h("label", { for: `pf-hook-${hk.name}` }, hk.label || hk.name),
      sel,
      h("div", { class: "field__hint" }, hk.description || ""));
  }));
}

export function renderModels(current = "") {
  const sel = $("pf-model");
  const names = new Set();
  const opts = [h("option", { value: "" }, "Par défaut (modèle de la session)")];
  for (const m of S.models) {
    if (names.has(m.name)) continue;
    names.add(m.name);
    opts.push(h("option", { value: m.name }, m.provider ? `${m.name} · ${m.provider}` : m.name));
  }
  if (current && !names.has(current)) opts.push(h("option", { value: current }, `${current} (introuvable)`));
  sel.replaceChildren(...opts);
  sel.value = current || "";
}

// ---------------------------------------------------------------- appliquer / collecter

/** Rend les contrôles qui dépendent du catalogue (à rappeler quand il change). */
export function renderCatalogControls() {
  renderPresets();
  renderTools();
  renderSkillChips();
  renderHooks();
  if ($("pf-fields").dataset.readonly === "true") setReadonly(true);
}

function appliquerHooks(hooks) {
  for (const hk of hooks || []) {
    const off = hk.startsWith("no-");
    const sel = document.querySelector(`#pf-hooks select[data-hook="${off ? hk.slice(3) : hk}"]`);
    if (sel) sel.value = off ? "off" : "on";
  }
}

/** Charge `profile` dans l'éditeur. Les sélections introuvables restent visibles et conservées. */
export function applyProfile(profile) {
  $("pf-name").value = profile.name || "";
  $("pf-desc").value = profile.description || "";
  $("pf-prompt").value = profile.system_prompt_extra || "";
  tools = new Set(profile.tools ? toolsOfProfile(profile, S.catalog) : presetTools("code", S.catalog));
  setSkills(profile.skills);
  renderCatalogControls();
  appliquerHooks(profile.hooks);
  renderModels(profile.model || "");
  $("pf-name-error").textContent = "";
  $("pf-name").removeAttribute("aria-invalid");
}

/** La charge utile envoyée au serveur (enregistrement et aperçu). */
export function collect() {
  const hooks = [];
  for (const sel of document.querySelectorAll("#pf-hooks select")) {
    if (sel.value === "on") hooks.push(sel.dataset.hook);
    else if (sel.value === "off") hooks.push(`no-${sel.dataset.hook}`);
  }
  const known = selectableTools(S.catalog).map((t) => t.name);
  // Ordre stable : catalogue puis introuvables — l'indicateur « modifié » ne bat pas pour rien.
  const orderedTools = [...known.filter((n) => tools.has(n)), ...[...tools].filter((n) => !known.includes(n)).sort()];
  return {
    name: $("pf-name").value.trim(),
    description: $("pf-desc").value.trim(),
    tools: orderedTools,
    skills: getSkills(),
    hooks,
    model: $("pf-model").value,
    system_prompt_extra: $("pf-prompt").value,
  };
}

/** L'état courant devient la référence (après chargement ou enregistrement). */
export function markClean() { baseline = JSON.stringify(collect()); }

/** Le formulaire diffère-t-il de la référence ? */
export function isDirty() { return baseline !== JSON.stringify(collect()); }

/** Lecture seule (profil fourni) : tout est désactivé, la sélection reste lisible. */
export function setReadonly(ro) {
  // Pas de <fieldset disabled> global : un profil fourni doit rester LISIBLE (texte
  // sélectionnable, liste d'outils dépliable), seulement pas modifiable.
  for (const el of $("pf-fields").querySelectorAll("input, textarea, select, button")) {
    if (el.id === "pf-customize" || el.id === "pf-tools-filter") continue;
    if ((el.tagName === "INPUT" && el.type !== "checkbox") || el.tagName === "TEXTAREA") el.readOnly = ro;
    else el.disabled = ro;
  }
  $("pf-fields").dataset.readonly = ro ? "true" : "false";
  for (const b of $("pf-skills-chips").querySelectorAll("button")) b.hidden = ro;
  $("pf-skills-search").hidden = ro;
}

/** Câble les écouteurs de l'éditeur (une fois). */
export function wireEditor() {
  const form = $("pf-form");
  form.addEventListener("submit", (e) => e.preventDefault());
  for (const id of ["pf-name", "pf-desc", "pf-prompt"]) $(id).addEventListener("input", edited);
  $("pf-model").addEventListener("change", edited);
  $("pf-customize").addEventListener("click", () => openTools($("pf-tools-panel").hidden));
  $("pf-tools-filter").addEventListener("input", applyToolFilter);
  wireSkillSearch(edited);
}
