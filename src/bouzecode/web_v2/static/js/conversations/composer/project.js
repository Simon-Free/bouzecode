// Bannière « projet » de la barre de nouvelle conversation, et présentation des
// suggestions quand /api/dispatch répond needs_project.

import { node } from "../dom.js";

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

function projectLabel(slug) {
  if (!slug) return "à choisir";
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
  // Le formulaire d'ajout et la liste des dossiers écartés : la route POST /api/projects
  // existait depuis toujours, mais aucun bouton ne l'appelait — seul un agent pouvait
  // enregistrer un projet.
  const { renderProjectsAdmin } = await import("/static/js/projects_admin.js");
  await renderProjectsAdmin();
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
  node(box, "span", "conv-project-suggestions-label", "Projet requis — suggestions :");
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
