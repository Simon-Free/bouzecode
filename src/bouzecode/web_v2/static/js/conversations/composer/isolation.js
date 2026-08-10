// Bannière « environnement » : le MÊME choix à trois valeurs que Agent(isolation=…)
// côté manager, pour que l'humain et le manager parlent la même langue.

import { node } from "../dom.js";

// --- Bannière "environnement" (isolation) ----------------------------------
// UN choix à TROIS valeurs, exactement celui que le manager passe à Agent(isolation=…) :
// humain et manager parlent ainsi la même langue. Remplace les anciennes cases à cocher
// « worktree » / « venv », dont le couple (pas de worktree, venv) n'avait aucun sens.
// Persisté en localStorage, injecté comme `isolation` dans le POST /api/dispatch.
const ISOLATION_STORAGE_KEY = "bz.conv.isolation";
const ISOLATION_CHOICES = [
  { value: "shared", desc: "Rien de provisionné : l'agent travaille dans le dépôt principal. Le plus rapide — pour un agent en lecture seule, une tâche courte, ou le seul écrivain." },
  { value: "worktree", desc: "Worktree git dédié, SANS venv. Dès que plusieurs agents écrivent en parallèle sur le même dépôt. Quasi gratuit." },
  { value: "worktree+venv", desc: "Worktree ET venv dédiés. Uniquement si l'agent touche aux dépendances (uv sync complet : ~30 s de lancement)." },
];
export let selectedIsolation = "shared";

function readStoredIsolation() {
  try { return localStorage.getItem(ISOLATION_STORAGE_KEY) || ""; } catch (_) { return ""; }
}

function renderIsolationPanel() {
  const panel = document.getElementById("conv-isolation-panel");
  const value = document.getElementById("conv-isolation-value");
  if (value) value.textContent = selectedIsolation;
  if (!panel) return;
  panel.replaceChildren();
  ISOLATION_CHOICES.forEach((choice) => {
    const opt = node(panel, "label", "conv-agent-option");
    const radio = node(opt, "input");
    radio.type = "radio";
    radio.name = "conv-isolation";
    radio.value = choice.value;
    radio.checked = choice.value === selectedIsolation;
    radio.addEventListener("change", () => {
      selectedIsolation = choice.value;
      try { localStorage.setItem(ISOLATION_STORAGE_KEY, choice.value); } catch (_) { /* privé/quota */ }
      if (value) value.textContent = choice.value;
    });
    const text = node(opt, "span", "conv-agent-option-text");
    node(text, "span", "conv-agent-option-name", choice.value);
    node(text, "span", "conv-agent-option-desc", choice.desc);
  });
}

export function wireIsolationBanner() {
  const stored = readStoredIsolation();
  selectedIsolation = ISOLATION_CHOICES.some((c) => c.value === stored) ? stored : "shared";
  renderIsolationPanel();
  const toggle = document.getElementById("conv-isolation-toggle");
  const panel = document.getElementById("conv-isolation-panel");
  if (!toggle || !panel) return;
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", open ? "false" : "true");
    panel.hidden = open;
  });
}
