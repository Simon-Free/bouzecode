// [desc] Bande d'action d'un point « qui t'attend » SANS tâche (/api/inbox : conversation libre, sous-agent, lancement hors tâche) : question ou plan, raison, et les gestes pour agir sur place (Répondre, Continuer, Relancer, Ouvrir la conversation). Aussi : rendu d'un plan d'agent, partagé avec les tâches. [/desc]
//
// Les points portés par une tâche passent par tache.js / tache_gestes.js (gestes par motif).

import { h, busy, toast, relTime } from "../lib/ui.js";
import { blocQuestion } from "./question.js";
import { rendreMarkdown } from "./markdown.js";
import * as act from "./actions.js";
import { ouvrirZoneMessage } from "./zone_message.js";

const PLAN_REPLIE_AU_DELA = 1200; // caractères : un plan plus long s'ouvre à la demande
const AIDE_CONTINUER = "Même agent, même conversation : il reprend là où il s'est arrêté.";
const AIDE_ARCHIVER = "L'agent est arrêté : classe cette question sans réponse (elle quitte « À traiter », sa trace reste).";

// ---------------------------------------------------------------- gestes

/** Bouton de geste : occupé pendant l'appel (sauf s'il ouvre une zone), erreur en toast. */
function bouton(label, cls, fn, attrs = {}, { dialogue = false } = {}) {
  const b = h("button", { type: "button", class: `btn btn--sm ${cls || ""}`, ...attrs }, label);
  const agir = async () => {
    try { await fn(b); } catch (e) { toast.err(`${label} : ${e.message}`); }
  };
  b.addEventListener("click", () => (dialogue ? agir() : busy(b, null, agir)));
  return b;
}

/** « Continuer… » : même agent, avec un message optionnel joint à la reprise (zone sous la bande). */
function gesteContinuer(item) {
  if (!item.agent_id) return null;
  return bouton("Continuer…", "btn--primary", async (b) => {
    ouvrirZoneMessage(b.closest("article") || b.parentElement, b.parentElement, {
      aria: "Message pour l'agent (optionnel)", bouton: "Continuer", occupe: "Reprise…",
      placeholder: "Message pour l'agent (optionnel)…",
      envoyer: async (text) => {
        try { await act.continuerAgent(item.agent_id, text); } catch (e) { throw new Error(`Reprise impossible : ${e.message}`); }
        act.toastAgent("L'agent reprend là où il s'était arrêté.", item.agent_id);
        await act.rafraichir();
      },
    });
  }, { title: AIDE_CONTINUER }, { dialogue: true });
}

function gesteRelancer(item) {
  if (!item.ticket_id || !item.projet_slug) return null;
  return bouton("Relancer", "btn--primary", async () => {
    const r = await act.relancerTicket(item.projet_slug, item.ticket_id);
    act.toastAgent("Lancement relancé.", (r && r.agent_id) || "");
    await act.rafraichir();
  }, { title: "Relance le lancement de cet agent (≈ 30 à 60 s), une fois la cause corrigée." });
}

/** « Acquitter » : retire un signalement de la liste — seul moyen de s'en défaire quand son
 *  agent n'existe plus (ou n'a jamais été un agent : pseudo-agent `process:<pid>`). */
function gesteAcquitter(item) {
  if (!item.signalement_id) return null;
  return bouton("Acquitter", "btn--ghost", async () => {
    await act.acquitterSignalement(item.signalement_id);
    toast.ok("Signalement acquitté.");
    window.dispatchEvent(new CustomEvent("ui:counts-changed"));
    await act.rafraichir();
  }, { title: "Retire ce signalement de la liste (il reste consultable dans son historique)." });
}

/** Un pseudo-agent de process (`process:<pid>`) n'a pas de conversation : rien à ouvrir. */
function aUneConversation(agentId) {
  return Boolean(agentId) && !String(agentId).startsWith("process:");
}

function lienOuvrir(item) {
  if (!aUneConversation(item.agent_id)) return null;
  return h("a", { class: "btn btn--ghost btn--sm", href: act.lienAgent(item.agent_id) }, "Ouvrir la conversation");
}

/** « Archiver… » : solde une question restée sans réponse d'un agent ARRÊTÉ, commentaire optionnel. */
function gesteArchiver(item) {
  if (!item.agent_id) return null;
  return bouton("Archiver…", "btn--ghost", async (b) => {
    ouvrirZoneMessage(b.closest("article") || b.parentElement, b.parentElement, {
      aria: "Commentaire d'archivage (optionnel)", bouton: "Archiver sans réponse", occupe: "Archivage…",
      placeholder: "Pourquoi tu la classes (optionnel)…",
      envoyer: async (text) => {
        try { await act.archiverQuestion(item.agent_id, text); } catch (e) { throw new Error(`Archivage impossible : ${e.message}`); }
        toast.ok("Question archivée sans réponse.");
        window.dispatchEvent(new CustomEvent("ui:counts-changed"));
        await act.rafraichir();
      },
    });
  }, { title: AIDE_ARCHIVER, "data-geste": "archiver" }, { dialogue: true });
}

function gestesDe(item) {
  const voulus = new Set(item.actions || []);
  return [voulus.has("continuer") ? gesteContinuer(item) : null, voulus.has("relancer") ? gesteRelancer(item) : null,
    voulus.has("acquitter") ? gesteAcquitter(item) : null,
    voulus.has("archiver") ? gesteArchiver(item) : null, lienOuvrir(item)].filter(Boolean);
}

// ---------------------------------------------------------------- contenu

/** Texte du plan de l'agent : ouvert s'il est court, replié (à la demande) s'il est long. */
export function blocPlan(plan) {
  if (!plan || !plan.trim()) return null;
  const nbLignes = plan.split("\n").length;
  return h("details", { class: "bz-plan", open: plan.length <= PLAN_REPLIE_AU_DELA },
    h("summary", null, `Plan proposé (${nbLignes} ligne${nbLignes > 1 ? "s" : ""})`), rendreMarkdown(plan));
}

function blocReponse(item) {
  const q = item.question || {};
  return blocQuestion(q, async (texte) => {
    await act.repondreAgent(item.agent_id, texte);
    window.dispatchEvent(new CustomEvent("ui:counts-changed"));
    setTimeout(() => act.rafraichir(), 1500);
  });
}

function corpsDe(item) {
  const attend = item.type === "question" || item.type === "plan";
  return [
    item.type === "plan" ? blocPlan((item.question || {}).plan) : null,
    attend ? blocReponse(item) : null,
  ].filter(Boolean);
}

/** Ce qu'il faut pour agir sur place : question / plan + rangée de gestes. */
export function contenuCarte(item) {
  const gestes = gestesDe(item);
  return [...corpsDe(item), gestes.length ? h("div", { class: "btn-row bz-attente__gestes" }, gestes) : null].filter(Boolean);
}

/** Ce qui, s'il change, justifie de reconstruire la bande. */
export function signature(item) {
  return JSON.stringify([item.type, item.motif, item.titre, item.question, item.raison, item.actions,
    item.ticket_id, relTime(item.depuis)]);
}

/** On n'y touche pas pendant qu'on y agit : bouton occupé, question en cours, texte en saisie. */
export function occupee(el) {
  if (!el) return false;
  if (el.querySelector("[aria-busy='true'], .bz-q[data-locked='true'], .bz-q[data-done='true']")) return true;
  const actif = document.activeElement;
  if (actif && el.contains(actif) && (actif.tagName === "TEXTAREA" || actif.tagName === "INPUT")) return true;
  const libre = el.querySelector(".bz-q__libre");
  return !!(libre && libre.value.trim());
}
