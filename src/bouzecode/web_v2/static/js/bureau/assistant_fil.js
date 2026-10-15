// [desc] Conversation de l'assistant du Bureau : état courant, mémoire locale, historique (reprendre / nouvelle), fil partagé (session_thread), question inline et suivi de la file d'attente. [/desc]
//
// Contrat serveur : fil lu par static/js/shared/session_thread.js (/blocks + /partial) ;
// historique GET /api/bureau/assistant/conversations ; réponse à une question
// POST /api/agents/<id>/messages {mode: "refuse"}.

import { h, api, relTime } from "../lib/ui.js";
import { agentState } from "../lib/states.js";
import { startSessionThread } from "../shared/session_thread.js";
import { blocQuestion, signatureQuestion } from "./question.js";
import * as act from "./actions.js";

const MEMOIRE = "bureau.assistant";

/** Nœuds du tiroir (renseignés par assistant.js au câblage). */
export const n = {};
/** Conversation courante. */
export const conv = { key: "", ticketId: "", fil: null, dernierEtat: "", sigQuestion: "", envoiEnCours: false };

export function lireMemoire(cle) {
  try { return localStorage.getItem(cle); } catch (_) { return null; }
}

export function ecrireMemoire(cle, valeur) {
  // Navigation privée : la conversation vit le temps de l'onglet (rien à signaler).
  try { if (valeur == null) localStorage.removeItem(cle); else localStorage.setItem(cle, valeur); } catch (_) { return false; }
  return true;
}

export function agentId() { return conv.key.replace(/^agent\//, ""); }

export function statut(texte) { if (n.statut) n.statut.textContent = texte || ""; }

// ---------------------------------------------------------------- historique

function optionsHistorique(items) {
  const premiere = conv.key ? "Conversation en cours" : (items.length ? "Nouvelle conversation" : "Aucune conversation passée");
  return [h("option", { value: "" }, premiere), ...items.filter((c) => c && c.key).map((c) => {
    const quand = relTime(c.started_at);
    return h("option", { value: c.key, "data-ticket": c.ticket_id || "" }, `${c.title || c.key}${quand ? ` — ${quand}` : ""}`);
  })];
}

export async function chargerHistorique() {
  const sel = n.hist;
  sel.disabled = true;
  sel.replaceChildren(h("option", { value: "" }, "Chargement de l'historique…"));
  let items;
  try {
    const d = await api("GET", "/api/bureau/assistant/conversations", undefined, { timeout: 15000 });
    items = (d && d.conversations) || [];
  } catch (e) {
    sel.replaceChildren(h("option", { value: "" }, "Historique indisponible"));
    sel.title = e.message;
    sel.disabled = false;
    return;
  }
  sel.replaceChildren(...optionsHistorique(items));
  sel.value = items.some((c) => c.key === conv.key) ? conv.key : "";
  sel.disabled = false;
}

function arreterFil() {
  if (conv.fil) { conv.fil.stop(); conv.fil = null; }
}

function oublierConversation() {
  arreterFil();
  if (n.stop) n.stop.hidden = true;
  Object.assign(conv, { key: "", ticketId: "", sigQuestion: "", dernierEtat: "" });
}

/** Reprend la conversation `key` : son fil s'affiche, le prochain message la continue. */
export function reprendre(key, ticketId) {
  oublierConversation();
  Object.assign(conv, { key, ticketId: ticketId || "" });
  n.fil.replaceChildren();
  ecrireMemoire(MEMOIRE, JSON.stringify({ key, ticket_id: conv.ticketId }));
  demarrerFil();
}

export function nouvelle(focus = true) {
  oublierConversation();
  ecrireMemoire(MEMOIRE, null);
  n.fil.replaceChildren(h("p", { class: "bz-assist__intro" },
    "Nouvelle conversation. Dis à l'assistant ce que tu veux : créer ou compléter une tâche, la lancer, faire le point…"));
  statut("");
  n.hist.value = "";
  if (focus) n.input.focus();
}

/** Au chargement : reprend la dernière conversation mémorisée, sinon en ouvre une nouvelle. */
export function restaurer() {
  let memo = null;
  try { memo = JSON.parse(lireMemoire(MEMOIRE) || "null"); } catch (_) { memo = null; }
  if (!memo || !memo.key) { nouvelle(false); return; }
  Object.assign(conv, { key: memo.key, ticketId: memo.ticket_id || "" });
  demarrerFil();
}

// ---------------------------------------------------------------- fil

function demarrerFil() {
  if (!conv.key) return;
  conv.fil = startSessionThread({
    key: conv.key,
    container: n.fil,
    onStatus: (st, _total, data) => surStatut(st || {}, data || {}),
  });
}

const attendReponse = (etat) => etat === "awaiting_input" || etat === "awaiting_plan_validation";

/** Pastille du bouton flottant : l'assistant attend ta réponse (visible même tiroir fermé). */
function majPastille(attend) {
  const pastille = n.bulle && n.bulle.querySelector(".bz-fab__pastille");
  if (!pastille) return;
  pastille.hidden = !attend;
  n.bulle.setAttribute("aria-label", attend ? "Ouvrir l'assistant — il attend ta réponse" : "Ouvrir l'assistant");
}

/** « Interrompre » n'existe que pendant que l'assistant joue un tour. */
function majStop(etat) {
  if (!n.stop || n.stop.getAttribute("aria-busy") === "true") return;
  n.stop.hidden = !(etat === "running" || etat === "starting");
}

function surStatut(st, data) {
  const etat = st.state || "";
  majPastille(attendReponse(etat));
  majStop(etat);
  if (etat === "running" || st.phase) statut(agentState({ state: etat, phase: st.phase }).label);
  else statut(attendReponse(etat) ? "L'assistant te pose une question." : "");
  // Fin d'un tour de l'assistant : il a pu créer / lancer des tâches → le Bureau se relit tout de suite.
  if (conv.dernierEtat === "running" && etat !== "running") act.rafraichir();
  conv.dernierEtat = etat;
  majQuestion(st);
  majFile(Array.isArray(data.queue) ? data.queue : null);
}

function questionDe(st) {
  if (!attendReponse(st.state) || !st.question) return null;
  return { texte: st.question, options: st.options || [], allow_freetext: st.allow_freetext !== false };
}

function majQuestion(st) {
  const q = questionDe(st);
  const actuel = n.fil.querySelector(".bz-assist__q");
  // Une réponse en cours ou envoyée ne se redessine pas ; elle part quand la question disparaît.
  if (actuel && actuel.querySelector(".bz-q[data-locked='true'], .bz-q[data-done='true']")) {
    if (!q) actuel.remove();
    return;
  }
  const sig = q ? signatureQuestion(q) : "";
  if (sig === conv.sigQuestion) return;
  conv.sigQuestion = sig;
  if (actuel) actuel.remove();
  if (!q) return;
  n.fil.appendChild(h("div", { class: "bz-assist__q" }, blocQuestion(q, async (texte) => {
    await api("POST", `/api/agents/${encodeURIComponent(agentId())}/messages`, { text: texte, mode: "refuse" }, { okField: true });
    if (conv.fil) conv.fil.reveiller();
  })));
  n.fil.scrollTop = n.fil.scrollHeight;
}

/** Marque « lu » les échos « en attente » dont le message a quitté la file serveur : la file ne
 *  lâche un message qu'une fois LU par l'assistant (relevé à sa frontière de tour). */
function majFile(file) {
  if (!file) return;
  const ids = new Set(file.map((x) => x.id));
  for (const el of n.fil.querySelectorAll(".bz-echo[data-queue-id]")) {
    if (ids.has(el.dataset.queueId)) continue;
    el.removeAttribute("data-queue-id");
    el.classList.remove("bz-echo--attente");
    el.classList.add("optimistic-echo");
    const etat = el.querySelector(".bz-echo__etat");
    if (etat) etat.textContent = "lu";
  }
}

/** Relance la lecture du fil tout de suite (après un envoi). */
export function reveillerFil() {
  if (conv.fil) conv.fil.reveiller();
}
