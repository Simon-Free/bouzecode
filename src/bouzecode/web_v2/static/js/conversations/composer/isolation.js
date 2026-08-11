// Bannière « environnement » : le MÊME choix à trois valeurs que Agent(isolation=…)
// côté manager, pour que l'humain et le manager parlent la même langue.

import { node } from "../dom.js";
import { t } from "../../i18n/index.js";

// --- Bannière "environnement" (isolation) ----------------------------------
// UN choix à TROIS valeurs, exactement celui que le manager passe à Agent(isolation=…) :
// humain et manager parlent ainsi la même langue. Remplace les anciennes cases à cocher
// « worktree » / « venv », dont le couple (pas de worktree, venv) n'avait aucun sens.
// Persisté en localStorage, injecté comme `isolation` dans le POST /api/dispatch.
const ISOLATION_STORAGE_KEY = "bz.conv.isolation";
// `value` est le CODE envoyé au serveur (Agent(isolation=…)) : il n'est JAMAIS traduit.
// Seule la description est du texte d'interface ; elle est résolue à chaque rendu, jamais
// au chargement du module, sinon une bascule de langue la laisserait figée.
const ISOLATION_CHOICES = [
  { value: "shared", descKey: "composer.isolation.shared_desc" },
  { value: "worktree", descKey: "composer.isolation.worktree_desc" },
  { value: "worktree+venv", descKey: "composer.isolation.worktree_venv_desc" },
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
    node(text, "span", "conv-agent-option-desc", t(choice.descKey));
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
