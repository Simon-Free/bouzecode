// [desc] Profils › Bibliothèque › Skills : liste, éditeur (nom verrouillé si existante, alerte « existe déjà »), enregistrer, supprimer. [/desc]
import { api, busy, toast, confirm as ask, h, skeleton, failed, empty, highlight } from "../lib/ui.js";
import { NAME_RE } from "./state.js";

const $ = (id) => document.getElementById(id);
const enc = encodeURIComponent;

let skills = [];
let cur = null; // {name, editable, source, isNew}
let baseline = "";
let onChanged = async () => {};

/** `changed()` est appelé après un enregistrement / une suppression (le catalogue de l'éditeur change). */
export function initSkills({ changed }) {
  onChanged = changed;
  $("pf-sk-filter").addEventListener("input", renderList);
  $("pf-sk-new").addEventListener("click", startNew);
  $("pf-sk-form").addEventListener("submit", (e) => { e.preventDefault(); save(); });
  $("pf-sk-delete").addEventListener("click", (e) => remove(e.currentTarget));
  $("pf-sk-content").addEventListener("input", refreshDirty);
  $("pf-sk-name").addEventListener("input", () => { $("pf-sk-name-error").textContent = ""; $("pf-sk-name").removeAttribute("aria-invalid"); refreshDirty(); });
  $("pf-sk-content").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); save(); }
  });
}

export function skillsDirty() { return !!cur && snapshot() !== baseline; }

function snapshot() { return `${$("pf-sk-name").value}\u0000${$("pf-sk-content").value}`; }
function refreshDirty() { $("pf-sk-dirty").textContent = skillsDirty() ? "• modifié" : ""; }

async function guard() {
  if (!skillsDirty()) return true;
  return ask({ title: "Abandonner les modifications de la skill ?", text: "Tes modifications non enregistrées seront perdues.",
    confirmLabel: "Abandonner", cancelLabel: "Continuer l'édition", danger: true });
}

export async function loadSkills() {
  skeleton($("pf-sk-list"), 5);
  try {
    skills = (await api("GET", "/api/skills")).skills || [];
  } catch (err) {
    failed($("pf-sk-list"), err, loadSkills, { title: "Liste des skills indisponible." });
    return;
  }
  renderList();
}

function renderList() {
  const q = $("pf-sk-filter").value.trim().toLowerCase();
  const rows = skills.filter((s) => !q || s.name.toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q));
  if (!rows.length) {
    empty($("pf-sk-list"), { title: q ? `Aucune skill ne correspond à « ${q} ».` : "Aucune skill.", inline: true });
    return;
  }
  $("pf-sk-list").removeAttribute("aria-busy");
  $("pf-sk-list").replaceChildren(...rows.map((s) => {
    const b = h("button", { type: "button", class: "pf-item", "data-name": s.name,
      "aria-current": cur && !cur.isNew && cur.name === s.name ? "true" : null },
    h("span", { class: "pf-item__name" }, s.editable ? "" : h("span", { "aria-hidden": "true" }, "🔒 "), s.name),
    h("span", { class: "pf-item__desc" }, s.description || s.source || ""));
    b.addEventListener("click", () => open(s.name));
    return b;
  }));
}

function showForm(meta) {
  $("pf-sk-empty").hidden = true;
  $("pf-sk-form").hidden = false;
  $("pf-sk-meta").textContent = meta;
  $("pf-sk-name-error").textContent = "";
  $("pf-sk-name").removeAttribute("aria-invalid");
}

async function open(name) {
  if (!(await guard())) return;
  const btn = $("pf-sk-list").querySelector(`.pf-item[data-name="${CSS.escape(name)}"]`);
  await busy(btn, null, async () => {
    let s;
    try {
      s = await api("GET", `/api/skills/${name.split("/").map(enc).join("/")}`);
    } catch (err) {
      toast.err(`Impossible d'ouvrir la skill « ${name} » : ${err.message}`);
      return;
    }
    cur = { name: s.name, editable: !!s.editable, source: s.source || "", isNew: false };
    $("pf-sk-name").value = s.name;
    $("pf-sk-name").readOnly = true;
    $("pf-sk-content").value = s.content || "";
    $("pf-sk-save").textContent = cur.editable ? "Enregistrer la skill" : "Enregistrer une copie globale";
    $("pf-sk-delete").hidden = !cur.editable;
    showForm(cur.editable ? "Skill globale — modifiable." : `Fournie (${cur.source || "externe"}) — l'enregistrer crée une copie globale qui la remplace.`);
    baseline = snapshot();
    refreshDirty();
    renderList();
  });
}

async function startNew() {
  if (!(await guard())) return;
  cur = { name: "", editable: true, source: "", isNew: true };
  $("pf-sk-name").value = "";
  $("pf-sk-name").readOnly = false;
  $("pf-sk-content").value = "---\nname: ma-skill\ndescription: Une ligne qui dit QUAND utiliser cette skill\n---\n\n# ma-skill\n\nInstructions de la skill…\n";
  $("pf-sk-save").textContent = "Créer la skill";
  $("pf-sk-delete").hidden = true;
  showForm("Nouvelle skill (non enregistrée).");
  baseline = "";
  refreshDirty();
  renderList();
  $("pf-sk-name").focus();
}

function nameError(msg, existing) {
  const err = $("pf-sk-name-error");
  err.replaceChildren(msg);
  if (existing) {
    const b = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, "Ouvrir la skill existante");
    b.addEventListener("click", () => { baseline = snapshot(); open(existing); });
    err.append(" ", b);
  }
  $("pf-sk-name").setAttribute("aria-invalid", "true");
  $("pf-sk-name").focus();
}

async function save() {
  if (!cur) return;
  const name = $("pf-sk-name").value.trim();
  if (!name) { nameError("Donne un nom à la skill."); return; }
  if (!NAME_RE.test(name)) { nameError("Minuscules, chiffres, - et _ uniquement."); return; }
  if (cur.isNew && skills.some((s) => s.name === name)) { nameError(`Une skill « ${name} » existe déjà.`, name); return; }
  await busy($("pf-sk-save"), "Enregistrement…", async () => {
    let data;
    try {
      data = await api("POST", "/api/skills", { name, content: $("pf-sk-content").value, create: cur.isNew });
    } catch (err) {
      if (err.status === 409) nameError(err.message, name);
      else toast.err(`Skill non enregistrée : ${err.message}`);
      return;
    }
    toast.ok(`Skill « ${data.name} » enregistrée.`);
    cur = { name: data.name, editable: true, source: "global", isNew: false };
    $("pf-sk-name").readOnly = true;
    $("pf-sk-save").textContent = "Enregistrer la skill";
    $("pf-sk-delete").hidden = false;
    $("pf-sk-meta").textContent = "Skill globale — modifiable.";
    baseline = snapshot();
    refreshDirty();
    await loadSkills();
    highlight($("pf-sk-list").querySelector(`.pf-item[data-name="${CSS.escape(data.name)}"]`));
    await onChanged();
  });
}

async function remove(btn) {
  if (!cur || cur.isNew || !cur.editable) return;
  const name = cur.name;
  const ok = await ask({ title: `Supprimer la skill « ${name} » ?`, danger: true, confirmLabel: "Supprimer",
    text: "Le fichier de la skill globale est effacé. Les profils qui la préchargent l'afficheront « introuvable »." });
  if (!ok) return;
  await busy(btn, "Suppression…", async () => {
    try {
      await api("DELETE", `/api/skills/${enc(name)}`);
    } catch (err) {
      toast.err(`Skill non supprimée : ${err.message}`);
      return;
    }
    toast.ok(`Skill « ${name} » supprimée.`);
    cur = null;
    baseline = "";
    $("pf-sk-form").hidden = true;
    $("pf-sk-meta").textContent = "";
    $("pf-sk-empty").hidden = false;
    refreshDirty();
    await loadSkills();
    await onChanged();
  });
}
