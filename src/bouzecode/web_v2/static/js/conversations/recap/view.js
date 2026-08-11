// Sous-onglet Récap : bascule de vue, chargement et rendu du payload servi par
// GET /api/sessions/<key>/recap. Le front n'ordonne RIEN — le serveur trie et
// regroupe. Le rendu des diffs eux-mêmes vit dans diff.js.

import { node } from "../dom.js";
import { openTabs } from "../state.js";
import { openTab, updateComposer } from "../panel/tabs.js";
import { renderDiffBlock } from "./diff.js";
import { t } from "../../i18n/index.js";

// --- Sous-onglet Récap : rendu 100% bête depuis le payload serveur ----------
// Le serveur (GET /api/sessions/<key>/recap) fait TOUT le tri/regroupement et
// renvoie {recap, recap_missing, diffs:[{file, patch, is_test, is_new, section}]}.
// Le front n'ordonne RIEN : il affiche les sections dans l'ordre reçu.

// Section servie par le serveur → CLÉ i18n. La table ne porte que des clés : le titre
// est composé au rendu, jamais au chargement du module (sinon la bascule de langue
// laisserait les anciens mots).
const RECAP_SECTION_KEYS = {
  changes: "panel.recap_section_changes",
  other: "panel.recap_section_other",
  tests: "panel.recap_section_tests",
  all: "panel.recap_section_all",
};

// Bascule le segmented control [Conversation | Recap]. Un seul pane visible à la
// fois. Sauve/restaure la position de scroll du fil pour un retour sans saut.
export function setView(key, view) {
  const entry = openTabs.get(key);
  if (!entry) return;
  if (view === "recap") {
    // Sauve la position du fil AVANT de le masquer, puis affiche le récap.
    entry.convScrollTop = entry.conv.scrollTop;
    entry.activeView = "recap";
    entry.paneConv.hidden = true;
    entry.paneRecap.hidden = false;
    fetchRecap(entry, key);
  } else {
    entry.activeView = "conv";
    entry.paneRecap.hidden = true;
    entry.paneConv.hidden = false;
    // Restaure la position de scroll mémorisée du fil.
    entry.conv.scrollTop = entry.convScrollTop;
  }
  if (entry.segConv) entry.segConv.classList.toggle("active", view === "conv");
  if (entry.segRecap) entry.segRecap.classList.toggle("active", view === "recap");
  updateComposer();
}

// Ouverte depuis la pastille de la sidebar / le CTA du bloc final. openTab a déjà
// créé l'entry (synchrone) — d'où l'appel openTab(key); openRecap(key) enchaîné.
// La pastille ouvre le récap AVANT même que la session soit détectée finished :
// on dégrise le bouton et on force la vue.
export function openRecap(key) {
  const entry = openTabs.get(key);
  if (!entry) return;
  if (entry.segRecap) { entry.segRecap.disabled = false; entry.segRecap.title = t("panel.recap_enabled_tip"); }
  setView(key, "recap");
}

function showConversation(key) {
  setView(key, "conv");
}

// Sur transition vers l'état terminal : dégrise le bouton Recap et injecte (une
// seule fois) le CTA « Voir le recap → » à la fin du fil. Idempotent.
export function maybeEnableRecap(entry, key) {
  if (entry.lastState !== "finished") return;
  if (entry.segRecap) { entry.segRecap.disabled = false; entry.segRecap.title = t("panel.recap_enabled_tip"); }
  if (entry.conv && !entry.conv.querySelector(".conv-recap-cta")) {
    const cta = node(entry.conv, "button", "conv-recap-cta", t("panel.recap_cta"));
    cta.type = "button";
    cta.addEventListener("click", () => openRecap(key));
  }
}

async function fetchRecap(entry, key) {
  if (entry.recapLoaded) return;
  entry.recapLoaded = true;
  entry.recapBody.replaceChildren();
  const loading = node(entry.recapBody, "div", "muted", t("panel.recap_loading"));
  try {
    const res = await fetch(`/api/sessions/${key}/recap`);
    const payload = await res.json();
    entry.recapBody.replaceChildren();
    renderRecap(entry.recapBody, payload);
  } catch (_) {
    loading.textContent = t("panel.recap_load_error");
    entry.recapLoaded = false; // permet une nouvelle tentative au prochain clic
  }
}

function renderRecap(root, payload) {
  // Vue MANAGER : concaténation des récaps des sous-agents (lot consolidé).
  if (payload && payload.is_aggregate && Array.isArray(payload.children)) {
    renderAggregateRecap(root, payload.children);
    return;
  }
  const recap = payload && payload.recap;
  const missing = !payload || payload.recap_missing;
  if (missing) {
    node(root, "div", "recap-banner", t("panel.recap_missing"));
  } else if (recap) {
    renderRecapText(root, recap);
  }
  renderRecapDiffs(root, (payload && payload.diffs) || []);
}

// Une carte par sous-agent (titre + sections texte + diffs), dans l'ordre de dispatch.
function renderAggregateRecap(root, children) {
  if (!children.length) {
    node(root, "div", "recap-banner", t("panel.recap_no_children"));
    return;
  }
  node(root, "div", "recap-agg-intro", t("panel.recap_agg_intro", { count: children.length }));
  for (const child of children) {
    const card = node(root, "div", "recap-child");
    const header = node(card, "div", "recap-child-header");
    // Titre cliquable → ouvre la conversation/récap de l'enfant (key = agent_id).
    const title = node(header, "h3", "recap-child-title", child.title || child.agent_id);
    if (child.agent_id) {
      title.classList.add("recap-child-link");
      title.title = t("panel.recap_open_child");
      title.addEventListener("click", () => {
        openTab(child.agent_id, child.title || child.agent_id, child.title);
        openRecap(child.agent_id);
      });
    }
    if (child.verdict) {
      node(header, "span",
        `recap-child-verdict recap-child-verdict-${String(child.verdict).toLowerCase()}`,
        child.verdict);
    }
    // Le front se base sur la présence effective du recap (plus robuste que has_recap,
    // et compatible avec les payloads qui n'exposent pas le flag).
    if (child.recap) {
      renderRecapText(card, child.recap);
      renderRecapDiffs(card, child.diffs || []);
    } else {
      node(card, "div", "recap-banner", t("panel.recap_child_missing"));
    }
  }
}

function renderRecapText(root, recap) {
  const sections = [
    ["panel.recap_symptoms", recap.symptoms],
    ["panel.recap_explanation", recap.explanation],
    ["panel.recap_section_tests", recap.tests],
  ];
  for (const [labelKey, value] of sections) {
    if (!value) continue;
    const box = node(root, "div", "recap-section");
    node(box, "h4", "recap-section-title", t(labelKey));
    node(box, "div", "recap-section-body", String(value));
  }
  const changes = Array.isArray(recap.changes) ? recap.changes : [];
  if (changes.length) {
    const box = node(root, "div", "recap-section");
    node(box, "h4", "recap-section-title", t("panel.recap_section_changes"));
    const list = node(box, "ol", "recap-changes");
    for (const ch of changes) {
      const li = node(list, "li", "recap-change");
      node(li, "code", "recap-change-file", (ch && ch.file) || "");
      const summary = ch && ch.summary;
      if (summary) node(li, "span", "recap-change-summary", " — " + summary);
    }
  }
}

function renderRecapDiffs(root, diffs) {
  let currentSection = null;
  for (const d of diffs) {
    if (d.section !== currentSection) {
      currentSection = d.section;
      const key = RECAP_SECTION_KEYS[currentSection] || RECAP_SECTION_KEYS.all;
      node(root, "h4", "recap-diff-section-title", t(key));
    }
    renderDiffBlock(root, d);
  }
}
