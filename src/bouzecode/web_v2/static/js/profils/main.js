// [desc] Profils (/agent-builder) : point d'entrée — chargement, sélection d'un profil, barre d'actions, garde « modifié », tiroirs. [/desc]
//
// SPEC §6 : maître/détail. Ce module ne fait que CÂBLER : l'éditeur (editor.js), l'aperçu
// en direct (preview.js), la liste (list.js), les actions (actions.js), le catalogue
// (catalog.js) et la bibliothèque (library_*.js).
import { api, busy, toast, confirm as ask, menu, skeleton, failed, highlight } from "../lib/ui.js";
import { S } from "./state.js";
import {
  wireEditor, onEdit, applyProfile, collect, markClean, isDirty, setReadonly, renderCatalogControls, renderModels,
} from "./editor.js";
import { initPreview, schedulePreview } from "./preview.js";
import { renderList, wireList, onSelect, itemOf } from "./list.js";
import {
  saveProfile, duplicateCurrent, exportProfile, importProfile, upgradePlugins, deleteProfile, nameError,
} from "./actions.js";
import { initCatalog } from "./catalog.js";
import { wireDrawers } from "./drawer.js";
import { initSkills, skillsDirty } from "./library_skills.js";
import { initPlugins } from "./library_plugins.js";
import { openLibrary, wireLibraryTabs } from "./library.js";
import { refreshHeader } from "./header.js";

const $ = (id) => document.getElementById(id);

function edited() {
  if ($("pf-name-error").textContent) nameError("");
  refreshHeader();
  schedulePreview();
}

// ---------------------------------------------------------------- garde « modifié »

async function guard() {
  if (S.current.mode === "readonly" || !isDirty()) return true;
  return ask({ title: "Abandonner les modifications ?", text: `Les modifications de « ${$("pf-title").textContent} » ne sont pas enregistrées.`,
    confirmLabel: "Abandonner", cancelLabel: "Continuer l'édition", danger: true });
}

window.addEventListener("beforeunload", (e) => {
  if ((S.current.mode !== "readonly" && isDirty()) || skillsDirty()) { e.preventDefault(); e.returnValue = ""; }
});

// ---------------------------------------------------------------- sélection

function show(profile, mode, { basedOn = "" } = {}) {
  S.current = { mode, name: mode === "new" ? "" : profile.name, basedOn, missing: profile.missing || { tools: [], skills: [] } };
  applyProfile(profile);
  setReadonly(mode === "readonly");
  markClean();
  renderList();
  refreshHeader();
  schedulePreview({ immediate: true });
}

async function select(name) {
  if (S.current.mode !== "new" && S.current.name === name) return;
  if (!(await guard())) return;
  const a = S.agents.find((x) => x.name === name);
  if (!a) { toast.err(`Profil « ${name} » introuvable.`); return; }
  showAgent(a);
  $("pf-editor").scrollTop = 0;
}

const PROFIL_VIDE = { name: "", description: "", system_prompt_extra: "", skills: [], hooks: [], model: "" };

function showAgent(a) { show(a, a.editable ? "edit" : "readonly"); }

async function newProfile() {
  if (!(await guard())) return;
  show(PROFIL_VIDE, "new");
  $("pf-name").focus();
}

// ---------------------------------------------------------------- chargements

async function loadAgents() {
  const data = await api("GET", "/api/builder/agents");
  S.agents = data.agents || [];
}

async function loadCatalogData() {
  S.catalog = await api("GET", "/api/builder/catalog");
  S.catalogLoaded = true;
}

/** Après un changement du catalogue (skill/plugin installé) : recharge sans perdre la saisie. */
async function catalogChanged() {
  const draft = collect();
  try {
    await Promise.all([loadCatalogData(), loadAgents()]);
  } catch (err) {
    toast.err(`Catalogue non rechargé : ${err.message}`);
    return;
  }
  const wasDirty = isDirty();
  applyProfile({ ...draft, tools: draft.tools.length ? draft.tools : undefined });
  if (!wasDirty) markClean();
  renderList();
  refreshHeader();
  schedulePreview();
}

async function boot() {
  skeleton($("pf-list"), 6);
  let models = [];
  try {
    [, , models] = await Promise.all([loadCatalogData(), loadAgents(),
      api("GET", "/api/models").then((d) => d.models || []).catch((err) => {
        toast.info(`Liste des modèles indisponible (${err.message}) : seul « par défaut » est proposé.`);
        return [];
      })]);
  } catch (err) {
    failed($("pf-list"), err, boot, { title: "Impossible de charger les profils." });
    toast.err(`Chargement des profils impossible : ${err.message}`);
    return;
  }
  S.models = models;
  renderModels("");
  renderCatalogControls();
  const wanted = new URL(location.href).searchParams.get("profil");
  const a = wanted && S.agents.find((x) => x.name === wanted);
  if (wanted && !a) toast.err(`Profil « ${wanted} » introuvable : nouveau profil ouvert à la place.`);
  if (a) showAgent(a); else show(PROFIL_VIDE, "new");
  if (location.hash === "#bibliotheque") openLibrary();
}

// ---------------------------------------------------------------- actions de la barre

async function onSave() {
  const name = await saveProfile();
  if (!name) return;
  try {
    await loadAgents();
  } catch (err) {
    toast.err(`Profil enregistré, mais la liste n'a pas pu être rechargée : ${err.message}`);
  }
  S.current = { ...S.current, mode: "edit", name, basedOn: "" };
  markClean();
  renderList();
  refreshHeader();
  highlight(itemOf(name));
}

function onDuplicate() {
  setReadonly(false);
  duplicateCurrent();
  refreshHeader();
  renderList();
  schedulePreview();
  $("pf-name").focus();
  $("pf-name").select();
}

async function onDelete() {
  const name = S.current.name;
  if (!(await deleteProfile(name))) return;
  try { await loadAgents(); } catch (err) { toast.err(`Liste non rechargée : ${err.message}`); }
  markClean();
  show(PROFIL_VIDE, "new");
}

function moreItems() {
  const { mode, name } = S.current;
  const saved = mode !== "new";
  return [
    { label: "Exporter (YAML)", fn: () => exportProfile(name), disabled: !saved,
      hint: saved ? "" : "Enregistre d'abord le profil." },
    { label: "Importer un profil…", fn: () => $("pf-import-file").click() },
    { label: "Mettre à jour les plugins de ce profil", fn: () => upgradePlugins(name), disabled: !saved },
    "sep",
    { label: "Supprimer…", danger: true, fn: onDelete, disabled: mode !== "edit",
      hint: mode === "edit" ? "" : "Seuls tes profils enregistrés se suppriment." },
  ];
}

async function onImportFile() {
  const input = $("pf-import-file");
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  if (!(await guard())) return;
  const t = toast.info(`Import de ${file.name}…`, { sticky: true });
  let text;
  try { text = await file.text(); } catch (err) { t.close(); toast.err(`Fichier illisible : ${err.message}`); return; }
  const name = await importProfile(text);
  t.close();
  if (!name) return;
  try { await loadAgents(); } catch (err) { toast.err(`Liste non rechargée : ${err.message}`); return; }
  markClean();
  const a = S.agents.find((x) => x.name === name);
  if (a) { showAgent(a); highlight(itemOf(name)); }
}

// ---------------------------------------------------------------- câblage

// La page occupe exactement la hauteur visible sous la nav ET les bandeaux (qui vont et viennent).
function fitHeight() {
  const top = $("main").getBoundingClientRect().top + window.scrollY;
  document.documentElement.style.setProperty("--pf-top", `${Math.round(top)}px`);
}
fitHeight();
if (typeof ResizeObserver !== "undefined") new ResizeObserver(fitHeight).observe($("banners"));
window.addEventListener("resize", fitHeight);

wireDrawers();
wireEditor();
wireList();
wireLibraryTabs();
initPreview(collect);
onEdit(edited);
onSelect(select);
initCatalog({
  onInstalled: async () => { await loadAgents(); renderList(); },
  onOpen: async (name) => {
    try { await loadAgents(); } catch (err) { toast.err(`Liste des profils non rechargée : ${err.message}`); }
    renderList();
    select(name);
  },
});
initSkills({ changed: catalogChanged });
initPlugins({ changed: catalogChanged });
menu($("pf-more"), moreItems);
$("pf-new").addEventListener("click", newProfile);
$("pf-save").addEventListener("click", onSave);
$("pf-duplicate").addEventListener("click", onDuplicate);
$("pf-fork").addEventListener("click", onDuplicate);
$("pf-import-file").addEventListener("change", onImportFile);
$("pf-library-open").addEventListener("click", openLibrary);
$("pf-use").addEventListener("click", async (e) => {
  if (!isDirty() || S.current.mode === "readonly") return;
  e.preventDefault();
  const ok = await ask({ title: "Profil modifié", text: "Tes modifications ne sont pas enregistrées : l'agent utilisera la version enregistrée.",
    confirmLabel: "Continuer quand même" });
  if (ok) { markClean(); location.href = $("pf-use").href; }
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    if (!$("pf-save").hidden && !$("pf-save").disabled) $("pf-save").click();
  }
});
if (typeof window !== "undefined") window.__profils = { S, collect, isDirty };
boot();
