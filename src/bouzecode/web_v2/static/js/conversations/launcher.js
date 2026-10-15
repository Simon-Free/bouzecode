// [desc] Barre de lancement d'une conversation libre : champ + chips toujours visibles (dépôt, profil, environnement), aucun dépôt deviné, envoi occupé, onglet ouvert AUSSITÔT sur l'agent en préparation, erreurs sous la barre sans perdre le texte. [/desc]

import { api, busy, lock, toast, menu } from "../lib/ui.js";
import { emit, countsChanged } from "./store.js";
import { ISOLATIONS, DEFAULT_ISOLATION, isolationLabel, normalizeIsolation, ticketBody, titleFromPrompt } from "./model.js";
import { recallText, rememberText } from "./memory.js";
import { openReposDialog } from "../projects_admin.js";

const K_REPO = "bz.conv.project";
const K_PROFILE = "bz.conv.typology";
const K_ENV = "bz.conv.isolation";
const NO_REPO_HINT = "Aucun dépôt choisi : l'agent ne sera pas lancé tant que tu n'en choisis pas un.";

const sel = { repo: "", profile: "", env: DEFAULT_ISOLATION };
const repos = { list: [], loaded: false, error: null };
let profiles = [];
let input, send, errorEl, chipRepo, chipProfile, chipEnv;

// ---------------------------------------------------------------- chips

function setChip(chip, label, title) {
  chip.firstElementChild.textContent = label;
  chip.setAttribute("aria-label", `${chip.dataset.what} : ${label}`);
  if (title !== undefined) chip.title = title;
}

function repoLabel(p) {
  if (p) return p.name || p.slug;
  if (!repos.loaded) return "chargement des dépôts…";
  return repos.list.length ? "choisir un dépôt" : "aucun dépôt : en ajouter un";
}

function paintChips() {
  const p = repos.list.find((x) => x.slug === sel.repo);
  setChip(chipRepo, repoLabel(p), p ? `${p.name || p.slug} — ${p.path || ""}` : NO_REPO_HINT);
  chipRepo.dataset.tone = p ? "" : "warn";
  const prof = profiles.find((t) => t.name === sel.profile);
  setChip(chipProfile, prof ? prof.name : (sel.profile || "default"));
  const env = ISOLATIONS.find((i) => i.value === sel.env);
  setChip(chipEnv, isolationLabel(sel.env), env ? env.hint : "");
}

// ---------------------------------------------------------------- dépôts

export async function loadProjects() {
  try {
    const data = await api("GET", "/api/projects", undefined, { timeout: 30000 });
    repos.list = (data && data.projects) || [];
    repos.error = null;
  } catch (err) {
    repos.error = err;
  }
  repos.loaded = true;
  // Le dernier dépôt utilisé est PROPOSÉ et AFFICHÉ ; jamais le « premier de la liste » deviné.
  const known = (slug) => repos.list.some((p) => p.slug === slug);
  const stored = recallText(K_REPO);
  sel.repo = [stored, sel.repo].find((slug) => slug && known(slug)) || "";
  paintChips();
  return repos.list;
}

function selectRepo(slug, project) {
  if (project && project.slug === slug && !repos.list.some((p) => p.slug === slug)) repos.list.push(project);
  sel.repo = slug;
  rememberText(K_REPO, slug);
  paintChips();
  if (errorEl.dataset.kind === "repo") showError("");
}

const info = (label) => ({ label, disabled: true, fn: () => {} });

function repoStatusItems() {
  if (!repos.loaded) return [info("Chargement des dépôts…")];
  if (repos.error) return [info(`Dépôts indisponibles : ${repos.error.message}`)];
  return repos.list.length ? [] : [info("Aucun dépôt enregistré")];
}

function repoItems() {
  const choices = repos.list.map((p) => ({
    label: `${p.slug === sel.repo ? "✓ " : ""}${p.name || p.slug}`, hint: p.path || p.description || "", fn: () => selectRepo(p.slug) }));
  return [{ label: "+ Ajouter un dépôt…", fn: openRepos }, "sep",
    ...repoStatusItems(), ...choices, "sep",
    { label: "Gérer les dépôts…", fn: openRepos }];
}

function openRepos() {
  openReposDialog({ onChange: loadProjects, onAdded: selectRepo });
}

// ---------------------------------------------------------------- profils

/** « Utiliser ce profil » (page Profils) ouvre /conversations?profil=<nom> : on le présélectionne puis on nettoie l'URL. */
function applyAskedProfile() {
  const url = new URL(location.href);
  const asked = url.searchParams.get("profil");
  if (!asked) return;
  if (profiles.some((t) => t.name === asked)) {
    sel.profile = asked;
    rememberText(K_PROFILE, asked);
    toast.info(`Profil « ${asked} » sélectionné pour la prochaine conversation.`);
    if (input) input.focus();
  } else {
    toast.err(`Profil « ${asked} » introuvable : le profil « ${sel.profile} » est utilisé.`);
  }
  url.searchParams.delete("profil");
  history.replaceState(null, "", url.toString());
}

async function loadProfiles() {
  try {
    const data = await api("GET", "/api/typologies", undefined, { timeout: 30000 });
    profiles = (data && data.typologies) || [];
  } catch (err) {
    profiles = [];
    toast.err(`Liste des profils indisponible (profil « default » utilisé) : ${err.message}`);
  }
  const stored = recallText(K_PROFILE);
  sel.profile = profiles.some((t) => t.name === stored) ? stored : ((profiles[0] && profiles[0].name) || "default");
  applyAskedProfile();
  paintChips();
}

function choose(what, key, value) {
  sel[what] = value;
  rememberText(key, value);
  paintChips();
}

// ---------------------------------------------------------------- lancement

function showError(msg, kind) {
  errorEl.textContent = msg;
  if (kind) errorEl.dataset.kind = kind; else delete errorEl.dataset.kind;
}

function autoGrow() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
}

/** Le serveur ne change plus d'environnement d'office (il refuse en 409 `collision_isolation`) ;
 *  il peut seulement retenir `shared` pour un dossier non git, ce qu'on dit alors. */
function announceIsolation(res) {
  const effective = normalizeIsolation(res.isolation || (res.ticket && res.ticket.isolation) || sel.env);
  if (effective === sel.env) return;
  toast.info(`Environnement retenu : ${isolationLabel(effective)}${res.isolation_message ? ` — ${res.isolation_message}` : ""}`);
}

function onLaunched(res, payload) {
  const key = res.launch_key || (res.ticket_id ? `launching/${res.ticket_id}` : res.key);
  input.value = "";
  autoGrow();
  toast.ok("Agent lancé : sa préparation s'affiche dans l'onglet.");
  announceIsolation(res);
  if (key) emit("open", { key, title: titleFromPrompt(payload.prompt), launch: payload });
  emit("refresh-tree");
  countsChanged();
}

async function onLaunchError(err) {
  if (!["depot_requis", "depot_inconnu", "projet_inconnu"].includes(err.code)) {
    showError(`Lancement impossible : ${err.message} (ton texte est conservé)`);
    return;
  }
  await loadProjects();
  showError(`${err.message} (ton texte est conservé)`, "repo");
  chipRepo.click();
}

/** Vérifie la saisie ; renvoie false (et dit pourquoi) si rien ne doit partir. */
function readyToLaunch(prompt) {
  if (!prompt) { showError("Écris d'abord ce que l'agent doit faire."); input.focus(); return false; }
  if (sel.repo) return true;
  showError("Choisis un dépôt pour lancer l'agent (ton texte est conservé).", "repo");
  chipRepo.focus();
  chipRepo.click();
  return false;
}

function createTicket(payload) {
  return api("POST", `/api/projects/${encodeURIComponent(payload.project_slug)}/tickets`, ticketBody(payload), { timeout: 60000 });
}

async function launch() {
  const prompt = input.value.trim();
  if (!readyToLaunch(prompt)) return;
  const payload = { prompt, project_slug: sel.repo, typology: sel.profile || "default", isolation: sel.env };
  await busy(send, "Lancement…", () => lock(input, async () => {
    showError("");
    try {
      onLaunched(await createTicket(payload), payload);
    } catch (err) {
      if (err.code === "isolation_impossible" && payload.isolation !== "shared") {
        //  Dossier non git : aucune copie isolée possible. On le DIT, puis on lance dans le dossier.
        toast.info("Ce dossier n'est pas un dépôt git : l'agent travaille directement dans le dossier.");
        try { onLaunched(await createTicket({ ...payload, isolation: "shared" }), payload); } catch (e2) { await onLaunchError(e2); }
        return;
      }
      await onLaunchError(err);
    }
  }));
}

// ---------------------------------------------------------------- câblage

function wireChipMenus() {
  menu(chipRepo, repoItems, { align: "left" });
  menu(chipProfile, () => (profiles.length ? profiles : [{ name: "default" }]).map((t) => ({
    label: `${t.name === sel.profile ? "✓ " : ""}${t.name}`, hint: t.description || "",
    fn: () => choose("profile", K_PROFILE, t.name) })), { align: "left" });
  menu(chipEnv, () => ISOLATIONS.map((i) => ({
    label: `${i.value === sel.env ? "✓ " : ""}${i.label}`, hint: i.hint,
    fn: () => choose("env", K_ENV, i.value) })), { align: "left" });
}

function wireInput(form) {
  form.addEventListener("submit", (e) => { e.preventDefault(); launch(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); launch(); }
  });
  input.addEventListener("input", () => {
    autoGrow();
    if (errorEl.textContent && errorEl.dataset.kind !== "repo") showError("");
  });
}

export function wireLauncher() {
  const form = document.getElementById("conv-new-bar");
  input = document.getElementById("conv-new-input");
  send = document.getElementById("conv-new-send");
  errorEl = document.getElementById("conv-new-error");
  chipRepo = document.getElementById("ag-chip-repo");
  chipProfile = document.getElementById("ag-chip-profile");
  chipEnv = document.getElementById("ag-chip-env");
  if (!form || !input) return;
  document.getElementById("ag-repo-add")?.addEventListener("click", openRepos);
  Object.assign(chipRepo.dataset, { what: "Dépôt" });
  Object.assign(chipProfile.dataset, { what: "Profil" });
  Object.assign(chipEnv.dataset, { what: "Environnement" });
  const storedEnv = recallText(K_ENV);
  sel.env = normalizeIsolation(storedEnv);
  wireInput(form);
  wireChipMenus();
  paintChips();
  loadProjects();
  loadProfiles();
}
