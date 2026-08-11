// Bannière « projet » de la barre de nouvelle conversation, et présentation des
// suggestions quand /api/dispatch répond needs_project.

import { node } from "../dom.js";
import { t } from "../../i18n/index.js";

// --- Bannière "projet" togglée --------------------------------------------
// Peuplée par GET /api/projects. Le dispatch ne devine PLUS le projet : l'utilisateur
// en choisit un explicitement, et il est injecté comme `project_slug` dans le POST
// /api/dispatch de newConversation(). La sélection est persistée en localStorage.
// Reste vide seulement quand aucun projet n'est ouvert → l'API répond needs_project.
const PROJECT_STORAGE_KEY = "bz.conv.project";
export let selectedProject = "";        // "" = aucun projet choisi (aucun projet ouvert)
let projects = [];               // dernier /api/projects

function readStoredProject() {
  try { return localStorage.getItem(PROJECT_STORAGE_KEY) || ""; } catch (_) { return ""; }
}
function storeProject(slug) {
  try { localStorage.setItem(PROJECT_STORAGE_KEY, slug); } catch (_) { /* privé/quota */ }
}

// Le nom d'un projet est une donnée de l'utilisateur : il n'est jamais traduit. Seul le
// libellé « aucun choix » l'est, et il est résolu à l'appel, pas au chargement du module.
function projectLabel(slug) {
  if (!slug) return t("composer.pick_one");
  const p = projects.find((x) => x.slug === slug);
  return (p && p.name) || slug;
}

function updateProjectValue() {
  const value = document.getElementById("conv-project-value");
  if (value) value.textContent = projectLabel(selectedProject);
}

function renderProjectPanel() {
  const panel = document.getElementById("conv-project-panel");
  if (!panel) return;
  panel.replaceChildren();
  // Aucun item synthétique "auto" : le dispatch ne déduit plus le projet, l'utilisateur
  // choisit TOUJOURS un projet réel (cf. selectedProject init dans loadProjects).
  projects.forEach((p) => {
    const opt = node(panel, "label", "conv-agent-option");
    const radio = node(opt, "input");
    radio.type = "radio";
    radio.name = "conv-project";
    radio.value = p.slug;
    radio.checked = p.slug === selectedProject;
    radio.addEventListener("change", () => {
      selectedProject = p.slug;
      storeProject(selectedProject);
      updateProjectValue();
    });
    const text = node(opt, "span", "conv-agent-option-text");
    node(text, "span", "conv-agent-option-name", p.name || p.slug);
    if (p.slug) node(text, "span", "conv-agent-option-desc", p.slug);
  });
  updateProjectValue();
}

export async function loadProjects() {
  try {
    const resp = await fetch("/api/projects");
    if (!resp.ok) return;
    const data = await resp.json();
    projects = data.projects || [];
  } catch (_) { projects = []; }
  // Restaure la sélection persistée si le slug existe encore ; sinon on retombe sur
  // le 1er projet réel. Aucun projet ouvert → "" et l'API répondra needs_project.
  const stored = readStoredProject();
  selectedProject = projects.some((p) => p.slug === stored)
    ? stored
    : (projects[0]?.slug || "");
  renderProjectPanel();
  renderAddProject();
}

// --- Ouvrir un projet depuis l'interface ------------------------------------
// `POST /api/projects` existe depuis toujours, mais aucun bouton ne l'appelait : seul un
// agent pouvait enregistrer un projet. Sans projet enregistré la page est un cul-de-sac —
// la bannière reste vide, le dispatch répond needs_project et n'a rien à suggérer.

async function postProject(body) {
  const resp = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  // Le serveur est monolingue : son refus (dossier introuvable, projet déjà ouvert) est
  // rendu tel quel, comme les noms de projets.
  if (!resp.ok) throw new Error(data.error || `POST /api/projects → ${resp.status}`);
  return data;
}

function addField(row, key, size) {
  const input = node(row, "input", "conv-projects-admin-input");
  input.type = "text";
  input.placeholder = t(key);
  input.setAttribute("aria-label", t(key));
  input.size = size;
  return input;
}

function renderAddProject() {
  const host = document.getElementById("conv-projects-admin");
  if (!host) return;
  host.replaceChildren();
  const row = node(host, "div", "conv-projects-admin-row");
  node(row, "span", "conv-projects-admin-label", t("composer.add_project"));
  const name = addField(row, "composer.project_name", 16);
  const path = addField(row, "composer.project_path", 34);
  const description = addField(row, "composer.project_description", 24);
  const button = node(row, "button", "conv-projects-admin-btn", t("composer.add"));
  button.type = "button";
  const error = node(host, "div", "conv-projects-admin-error");

  button.addEventListener("click", async () => {
    error.textContent = "";
    if (!name.value.trim() || !path.value.trim()) {
      error.textContent = t("composer.name_and_path_required");
      return;
    }
    try {
      await postProject({
        name: name.value.trim(),
        path: path.value.trim(),
        description: description.value.trim(),
      });
    } catch (e) {
      // Le refus est la RÉPONSE attendue de ce formulaire : on l'affiche, on ne l'avale pas.
      error.textContent = e.message;
      return;
    }
    // Recharge la liste : le projet neuf apparaît dans les radios, et ce bloc est redessiné
    // vide (les champs saisis disparaissent avec lui).
    await loadProjects();
  });
}

export function wireProjectBanner() {
  const toggle = document.getElementById("conv-project-toggle");
  const panel = document.getElementById("conv-project-panel");
  if (!toggle || !panel) return;
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", open ? "false" : "true");
    panel.hidden = open;
    // SPEC5 : rafraîchir la liste projets à chaque ouverture de la bannière.
    if (!open) loadProjects();
  });
}

function openProjectBanner() {
  const toggle = document.getElementById("conv-project-toggle");
  const panel = document.getElementById("conv-project-panel");
  if (toggle) toggle.setAttribute("aria-expanded", "true");
  if (panel) panel.hidden = false;
}

// SPEC4 : dispatch a répondu needs_project → ouvrir la bannière, surligner le
// sélecteur et afficher les suggestions renvoyées (au lieu d'un échec muet).
export function showProjectSuggestions(suggestions) {
  openProjectBanner();
  const toggle = document.getElementById("conv-project-toggle");
  if (toggle) toggle.classList.add("conv-project-needs");
  const box = document.getElementById("conv-project-suggestions");
  if (!box) return;
  box.replaceChildren();
  box.hidden = false;
  node(box, "span", "conv-project-suggestions-label", t("composer.project_required"));
  (suggestions || []).forEach((s) => {
    const slug = typeof s === "string" ? s : (s.slug || "");
    const name = typeof s === "string" ? s : (s.name || s.slug || "");
    const btn = node(box, "button", "conv-project-suggestion", name);
    btn.type = "button";
    btn.dataset.slug = slug;
    btn.addEventListener("click", () => {
      selectedProject = slug;
      storeProject(slug);
      renderProjectPanel();
    });
  });
}
