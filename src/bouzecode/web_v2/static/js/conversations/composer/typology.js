// Bannière « type d'agent » de la barre de nouvelle conversation.

import { node } from "../dom.js";

// --- Bannière "type d'agent" togglée ---------------------------------------
// Peuplée par GET /api/typologies. Le 1er item ("default" = agent de code) est
// le défaut. La sélection est persistée en localStorage et injectée comme
// `typology` dans le POST /api/dispatch de newConversation().
const TYPOLOGY_STORAGE_KEY = "bz.conv.typology";
export let selectedTypology = "";       // "" = default / agent de code
let typologies = [];             // dernier /api/typologies

function readStoredTypology() {
  try { return localStorage.getItem(TYPOLOGY_STORAGE_KEY) || ""; } catch (_) { return ""; }
}
function storeTypology(name) {
  try { localStorage.setItem(TYPOLOGY_STORAGE_KEY, name); } catch (_) { /* privé/quota */ }
}

// AUCUN texte de ce fichier n'est traduit, et c'est délibéré. Le catalogue servi par
// /api/typologies est OUVERT : chaque profil YAML posé par un utilisateur (projet, global,
// dossiers extra) y ajoute une entrée dont le `name` est le nom de fichier et la
// `description` un extrait de son prompt. Il n'existe donc aucun identifiant stable
// distinct du nom sur lequel accrocher une clé de traduction, et traduire les seuls
// intégrés donnerait un panneau moitié anglais moitié langue de l'auteur du profil.
// Les libellés restent ceux du serveur ; "default" est un code, pas un mot d'interface.
function typologyLabel(name) {
  const t = typologies.find((x) => x.name === name);
  return (t && t.name) || (typologies[0] && typologies[0].name) || "default";
}

function updateAgentValue() {
  const value = document.getElementById("conv-agent-value");
  if (value) value.textContent = typologyLabel(selectedTypology);
}

function renderTypologyPanel() {
  const panel = document.getElementById("conv-agent-panel");
  if (!panel) return;
  panel.replaceChildren();
  typologies.forEach((t) => {
    const opt = node(panel, "label", "conv-agent-option");
    const radio = node(opt, "input");
    radio.type = "radio";
    radio.name = "conv-typology";
    radio.value = t.name;
    radio.checked = t.name === selectedTypology
      || (!selectedTypology && t.name === (typologies[0] && typologies[0].name));
    radio.addEventListener("change", () => {
      // "default" (1er item) → typology vide = comportement dispatcher par défaut.
      selectedTypology = t.name === (typologies[0] && typologies[0].name) ? "" : t.name;
      storeTypology(selectedTypology);
      updateAgentValue();
    });
    const text = node(opt, "span", "conv-agent-option-text");
    node(text, "span", "conv-agent-option-name", t.name);
    if (t.description) node(text, "span", "conv-agent-option-desc", t.description);
  });
  updateAgentValue();
}

export async function loadTypologies() {
  try {
    const resp = await fetch("/api/typologies");
    if (!resp.ok) return;
    const data = await resp.json();
    typologies = data.typologies || [];
  } catch (_) { typologies = []; }
  // Restaure la sélection persistée si elle existe encore, sinon défaut (1er).
  const stored = readStoredTypology();
  selectedTypology = typologies.some((t) => t.name === stored) ? stored : "";
  renderTypologyPanel();
}

export function wireAgentBanner() {
  const toggle = document.getElementById("conv-agent-toggle");
  const panel = document.getElementById("conv-agent-panel");
  if (!toggle || !panel) return;
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", open ? "false" : "true");
    panel.hidden = open;
  });
}
