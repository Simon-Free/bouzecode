// Onglets internes : ouverture, activation, fermeture, et construction du panneau
// de conversation (fil, rail sous-agents, bloc question, composer, contrôle de relance).

import { node, agentId } from "../dom.js";
import { openTabs, activeKey, setActiveKey } from "../state.js";
import { refreshList } from "../sidebar/list.js";
import { sendMsg } from "./send.js";
import { poll } from "./poll.js";
import { pollPartial } from "./streaming.js";
import { buildSessionMenu } from "./meta.js";
import { setView } from "../recap/view.js";
import { createRelaunchControl } from "../../conv_relaunch.js";
import { t } from "../../i18n/index.js";

// --- Onglets internes -------------------------------------------------------

// [B5] Layout : quand un onglet est ouvert on replie le composer "nouvelle
// conversation" + la bannière type d'agent (via la classe .tabs-open sur
// .conv-main) pour rendre la hauteur au chat. `composerForced` vaut true quand
// l'utilisateur a explicitement rouvert le composer via le bouton "+".
export let composerForced = false;
export function setComposerForced(forced) { composerForced = forced; }

// La barre de lancement d'agent (prompt + Type d'agent + Projet) reste TOUJOURS
// VISIBLE, même avec des onglets ouverts (la règle CSS qui la masquait en
// .tabs-open a été supprimée). `.tabs-open` ne sert plus qu'au mode COMPACT du
// composer (padding réduit) quand au moins un onglet est ouvert.
export function updateComposer() {
  const main = document.querySelector(".conv-main");
  if (!main) return;
  main.classList.toggle("tabs-open", openTabs.size > 0);
}

export function activateTab(key) {
  setActiveKey(key);
  openTabs.forEach((t, k) => {
    t.tab.classList.toggle("active", k === key);
    t.panel.hidden = k !== key;
  });
  document.querySelectorAll(".conv-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.key === key);
    el.classList.toggle("open", openTabs.has(el.dataset.key) && el.dataset.key !== key);
  });
  const empty = document.querySelector(".conv-empty");
  if (empty) empty.hidden = true;
  updateComposer();
}

export function closeTab(key) {
  const t = openTabs.get(key);
  if (!t) return;
  clearTimeout(t.poller);
  clearTimeout(t.partialPoller);
  t.tab.remove();
  t.panel.remove();
  openTabs.delete(key);
  const next = [...openTabs.keys()].pop();
  if (next) activateTab(next);
  else {
    setActiveKey(null);
    composerForced = false;
    const empty = document.querySelector(".conv-empty");
    if (empty) empty.hidden = false;
  }
  updateComposer();
  refreshList(true);
}

async function interruptActive() {
  if (!activeKey) return;
  const entry = openTabs.get(activeKey);
  try {
    await fetch(`/api/agents/${agentId(activeKey)}/interrupt`, { method: "POST" });
    if (entry && entry.input) entry.input.focus();
  } catch (_) { /* réseau : on ignore */ }
}

// Ctrl+C global : interrompt l'onglet actif SI rien n'est sélectionné.
// Si du texte est sélectionné, on laisse la copie native se faire.
document.addEventListener("keydown", (e) => {
  const isCopy = (e.ctrlKey || e.metaKey) && (e.key === "c" || e.key === "C");
  if (!isCopy) return;
  const sel = window.getSelection();
  if (sel && sel.toString() !== "") return; // texte sélectionné → copie native
  if (!activeKey) return;
  e.preventDefault();
  interruptActive();
});

export function openTab(key, title, titleFull) {
  if (openTabs.has(key)) { activateTab(key); return; }

  const tabsBar = document.getElementById("conv-tabs");
  const tab = node(tabsBar, "div", "conv-tab");
  // Deux sous-agents du même profil produisaient des onglets « Validateur · python-coder »
  // strictement identiques. On garde le rôle court dans le label (le profil et l'heure
  // vont dans le tooltip) et on ajoute l'id court (8 hex, mono, gris) qui rend chaque
  // onglet unique. Le sujet/rôle prend l'ellipsis ; l'id n'est JAMAIS tronqué (CSS).
  // L'id court (#xxxxxxxx) n'est plus affiché DANS l'onglet : il apparaissait aussi dans
  // la ligne meta, sous une AUTRE troncature, ce qui laissait croire à deux identifiants
  // distincts (id de session vs id d'agent). L'onglet ne garde que le rôle ; l'id complet
  // reste dans le tooltip (info préservée). L'unique chip cliquable→copie vit dans renderMeta.
  const roleShort = ((title || "").split("·")[0].trim()) || title || key;
  tab.title = [titleFull || title || key, "#" + agentId(key)].filter(Boolean).join(" · ");
  node(tab, "span", "conv-tab-title", roleShort);
  const close = node(tab, "span", "conv-tab-close", "×");
  tab.addEventListener("click", (e) => {
    if (e.target !== close) activateTab(key);
  });
  close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(key); });

  const panels = document.getElementById("conv-panels");
  const panel = node(panels, "div", "conv-panel");
  const status = node(panel, "div", "conv-panel-status");
  // Menu "document" persistant (créé une fois, hors du replaceChildren de poll()).
  // Il contient le chemin complet du session.json (sélectionnable) + Copier + Télécharger.
  // Le bouton .conv-meta-doc, lui reconstruit à chaque poll dans la ligne meta, le toggle.
  const metaMenu = node(panel, "div", "conv-meta-menu");
  metaMenu.hidden = true;
  buildSessionMenu(metaMenu, key);

  // Vue Conversation (par défaut) + vue Récap (ouverte depuis la pastille de la sidebar).
  // Plus de barre de sous-onglets : elle gâchait une ligne sur CHAQUE conversation alors
  // qu'une minorité a un récap. Le front reste bête : le serveur trie/regroupe les diffs
  // (payload {recap, recap_missing, diffs:[{file, patch, is_test, is_new, section}]}).
  // Segmented control [Conversation | Recap] dans l'en-tête du panneau : un seul
  // pane visible à la fois, pleine hauteur. Remplace l'ancien lien « ← conversation ».
  // viewSwitch créé DÉTACHÉ (pas node(panel,...)) : il ne doit JAMAIS être une ligne
  // dédiée du panneau. renderMeta l'appendChild dans la ligne meta .conv-panel-status
  // (appendChild déplace le nœud existant → listeners + état disabled survivent au poll,
  // qui ne fait que replaceChildren du CONTENU de status puis ré-append le switch).
  const viewSwitch = document.createElement("div");
  viewSwitch.className = "conv-view-switch";
  const segConv = node(viewSwitch, "button", "conv-view-btn active", t("panel.view_conversation"));
  segConv.type = "button";
  segConv.dataset.view = "conv";
  const segRecap = node(viewSwitch, "button", "conv-view-btn", t("panel.view_recap"));
  segRecap.type = "button";
  segRecap.dataset.view = "recap";
  // Recap grisé tant que la session n'est pas terminée (dégrisé par maybeEnableRecap).
  segRecap.disabled = true;
  segRecap.title = t("panel.recap_disabled_tip");
  segConv.addEventListener("click", () => setView(key, "conv"));
  segRecap.addEventListener("click", () => { if (!segRecap.disabled) setView(key, "recap"); });

  const paneConv = node(panel, "div", "conv-pane-conv");
  const paneRecap = node(panel, "div", "conv-pane-recap");
  paneRecap.hidden = true;
  const recapBody = node(paneRecap, "div", "conv-recap-body");

  const conv = node(paneConv, "div", "conv-messages");

  // Conteneur du rail de sous-agents (entry.sub). Le rail lui-même a été retiré de
  // l'interface — plus personne ne le peuple — mais `entry` référence toujours `sub` :
  // sans cette ligne, openTab levait `ReferenceError: sub is not defined` et le panneau
  // ne se montait pas du tout (régression gardée par conversations.subrail.test.js).
  const sub = node(paneConv, "div", "conv-sub-rail");

  // Marqueurs inline de lancement/complétion de sous-agents (bloc .subagent-event
  // rendu par le backend). Le HTML est injecté via insertAdjacentHTML → aucun listener
  // n'est attaché : on délègue le clic ici pour ouvrir l'onglet du sous-agent ciblé.
  conv.addEventListener("click", (e) => {
    const el = e.target.closest("[data-open-key]");
    if (!el || !conv.contains(el)) return;
    const openKey = el.getAttribute("data-open-key");
    if (!openKey) return;
    openTab(openKey, el.textContent.trim() || openKey);
  });

  const question = node(paneConv, "div", "conv-question");
  question.hidden = true;
  const questionText = node(question, "div", "conv-question-text");
  const questionPlan = node(question, "div", "conv-question-plan");
  questionPlan.hidden = true;
  const questionOptions = node(question, "div", "conv-question-options");

  const footer = node(paneConv, "div", "conv-input");
  const input = node(footer, "textarea", "conv-input-box");
  input.id = "conv-input-" + key;
  input.name = "conv-input";
  input.placeholder = t("panel.input_placeholder");
  input.rows = 2;
  const send = node(footer, "button", "conv-input-send", t("panel.send"));
  const inputError = node(footer, "div", "conv-input-error");

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMsg(key);
    }
  });
  send.addEventListener("click", () => sendMsg(key));

  // Contrôle de RELANCE (ticket dont l'agent est mort). Créé DÉTACHÉ et persistant,
  // comme viewSwitch : renderMeta l'appendChild dans la ligne meta à chaque poll
  // (appendChild déplace le nœud → listeners et état « relance en cours » survivent).
  const relaunch = createRelaunchControl({
    fetch: (url, init) => fetch(url, init),
    confirm: (message) => window.confirm(message),
    onLaunched: (newKey) => openTab(newKey, t("panel.relaunch_tab")),
  });

  const entry = { tab, panel, conv, status, sub, metaMenu, key, input, inputError, question, questionText, questionPlan, questionOptions, paneConv, paneRecap, recapBody, viewSwitch, segConv, segRecap, relaunch, activeView: "conv", convScrollTop: 0, recapLoaded: false, nextIndex: 0, lastState: "cli", questionSignature: "", poller: null, partialPoller: null, partialActive: true, polling: false };
  openTabs.set(key, entry);
  activateTab(key);
  poll(key);
  pollPartial(key);
}
