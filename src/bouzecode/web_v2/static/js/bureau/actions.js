// [desc] Gestes métier du Bureau (tâches, chantiers, agents) : un appel API + le toast de résultat, partagés par la boîte « À traiter » et les tâches. [/desc]
//
// Chaque fonction lève en cas d'échec (ApiError au message lisible) : l'appelant l'enveloppe
// dans ui.busy(bouton) et affiche l'erreur là où l'utilisateur regarde (R4). Après toute
// écriture, `rafraichir()` relit le Bureau tout de suite (R3 : résultat visible sans recharger)
// et prévient la nav (pastilles).

import { api, toast } from "../lib/ui.js";

let refresh = async () => {};

/** Branché par main.js : relit /api/lignes + /api/inbox immédiatement. */
export function setRefresh(fn) { refresh = fn; }

export async function rafraichir() {
  window.dispatchEvent(new CustomEvent("ui:counts-changed"));
  await refresh();
}

const enc = encodeURIComponent;

// ---------------------------------------------------------------- tâches

export function creerTache({ titre = "", corps = "", macro_id = "", projet_slug = "" }) {
  return api("POST", "/api/micros", { titre, corps, macro_id, projet_slug });
}

export function modifierTache(id, champs) {
  return api("PATCH", `/api/micros/${enc(id)}`, champs);
}

export function changerEtat(id, etat, pourquoi = "") {
  return api("POST", `/api/micros/${enc(id)}/etat`, { etat, pourquoi });
}

const compte = (v) => (Array.isArray(v) ? v.length : Number(v) || 0);

/** « — 2 agents archivés » / « — 1 agent restauré » d'après la réponse de /etat (archivage en
 *  cascade des agents de la tâche) ; "" si le serveur n'en dit rien. */
export function suffixeArchivage(r) {
  const bloc = r && (r.archives || r.restaures);
  if (!bloc) return "";
  const n = compte(bloc.conversations) || compte(bloc.tickets);
  if (!n) return "";
  const verbe = r.archives ? "archivé" : "restauré";
  return ` — ${n} agent${n > 1 ? "s" : ""} ${verbe}${n > 1 ? "s" : ""}`;
}

/** Rouvre une tâche classée (restaure ses agents archivés) et le dit. */
export async function rouvrirTache(id) {
  const r = await changerEtat(id, "brouillon");
  toast.ok(`Tâche rouverte${suffixeArchivage(r)}.`);
  await rafraichir();
}

/** Classe une tâche (faite / abandonnée), le dit avec le nombre d'agents archivés, et propose Annuler (= Rouvrir). */
export async function classerTache(id, etat, libelle, pourquoi = "") {
  const r = await changerEtat(id, etat, pourquoi);
  toast.ok(`${libelle}${suffixeArchivage(r)}.`, { action: { label: "Annuler", fn: () => rouvrirTache(id) } });
  await rafraichir();
}

/** Classe la tâche sans la lancer, en disant pourquoi (motif faite | doublon | caduque). */
export function classerAvecCommentaire(id, motif, { commentaire = "", de = "" } = {}) {
  return api("POST", `/api/micros/${enc(id)}/classer`, { motif, commentaire, de, auteur: "humain" });
}

/** `execution` (facultatif) : {cible: local|rundeck, projets, fichiers_non_suivis, mode?, commande?, navigateur?}. */
export function lancerTache(id, { projet_slug = "", profil = "", isolation = "", execution = null } = {}) {
  const corps = { projet_slug, profil, isolation, ...(execution ? { execution } : {}) };
  return api("POST", `/api/micros/${enc(id)}/lancer`, corps, { okField: true, timeout: 90000 });
}

export function relancerTache(id, { retour = "", mode = "", projet_slug = "", profil = "", isolation = "", execution = null } = {}) {
  const corps = { retour, mode, projet_slug, profil, isolation, ...(execution ? { execution } : {}) };
  return api("POST", `/api/micros/${enc(id)}/relancer`, corps, { okField: true, timeout: 90000 });
}

/** Fichiers NON SUIVIS d'un projet (proposés, secrets signalés) — service de l'outil `Projets`. */
export function fichiersNonSuivis(slug, indices = "") {
  const q = indices ? `?indices=${enc(indices)}` : "";
  return api("GET", `/api/projects/${enc(slug)}/fichiers-non-suivis${q}`);
}

export function apercuPrompt(id, retour = "") {
  const q = retour ? `?retour=${enc(retour)}` : "";
  return api("GET", `/api/micros/${enc(id)}/prompt${q}`);
}

export function arreterTache(id) {
  return api("POST", `/api/micros/${enc(id)}/arreter`, {}, { okField: true, timeout: 30000 });
}

/** L'intégration part EN FOND (202, état `integrating`) : on annonce qu'elle est lancée, jamais
 *  qu'elle est faite — l'état du passage se met à jour au rafraîchissement suivant. */
export function messageIntegration(res) {
  if (res && res.state && res.state !== "integrating") return res.message || "Intégration terminée.";
  return "Intégration en cours : la fusion se fait en fond, l'état du passage se mettra à jour.";
}

export function integrerPassage(id, ticketId) {
  return api("POST", `/api/micros/${enc(id)}/passages/${enc(ticketId)}/integrer`, {}, { okField: true, timeout: 120000 });
}

/** Crée la tâche d'un point du récap d'un passage (« reste à faire » / « à décider »). */
export function creerSuite(id, ticketId, libelle, decision) {
  return api("POST", `/api/micros/${enc(id)}/passages/${enc(ticketId)}/suites`, { libelle, decision }, { okField: true });
}

// ---------------------------------------------------------------- chantiers

export function creerChantier(titre) {
  return api("POST", "/api/macros", { titre });
}

export function modifierChantier(id, champs) {
  return api("PATCH", `/api/macros/${enc(id)}`, champs);
}

export function supprimerChantier(id) {
  return api("DELETE", `/api/macros/${enc(id)}`);
}

export function reordonnerChantiers(ordre) {
  return api("POST", "/api/macros/reorder", { ordre });
}

export function ajouterDepot(id, slug) {
  return api("POST", `/api/macros/${enc(id)}/projets`, { slug });
}

export function retirerDepot(id, slug) {
  return api("DELETE", `/api/macros/${enc(id)}/projets/${enc(slug)}`);
}

// ---------------------------------------------------------------- agents

/** Répond à la question d'un agent (option ou texte libre). */
export function repondreAgent(agentId, text) {
  return api("POST", `/api/agents/${enc(agentId)}/messages`, { text, mode: "refuse" }, { okField: true });
}

/** Fait reprendre un agent arrêté sans finir, dans la même conversation. */
export function continuerAgent(agentId, text = "") {
  return api("POST", `/api/agents/${enc(agentId)}/messages`, { text, mode: "refuse" }, { okField: true });
}

/** Classe SANS réponse la question d'un agent arrêté (commentaire optionnel) : elle quitte « À traiter ». */
export function archiverQuestion(agentId, comment = "") {
  return api("POST", `/api/agents/${enc(agentId)}/question/archive`, { comment });
}

/** Relance un ticket dont le lancement a échoué (hors tâche). */
export function relancerTicket(slug, ticketId) {
  return api("POST", `/api/projects/${enc(slug)}/tickets/${enc(ticketId)}/runs`, {}, { okField: true, timeout: 120000 });
}

/** Demande l'annulation (rollback) d'un passage intégré : crée la tâche de revert, idempotent. */
export function demanderRollback(id, ticketId, motif = "") {
  return api("POST", `/api/micros/${enc(id)}/passages/${enc(ticketId)}/revert`, { motif }, { okField: true });
}

/** Émet un signalement humain (info / alerte / bloquant), comme l'outil Signaler d'un agent. */
export function creerSignalement(donnees) {
  return api("POST", "/api/signalements", donnees, { okField: true });
}

/** Acquitte un signalement : il sort de « Ce qui t'attend » (sa fiche reste consultable). */
export function acquitterSignalement(signalementId) {
  return api("POST", `/api/signalements/${enc(signalementId)}/acquitter`, {}, { okField: true });
}

/** Toast de lancement : reste 10 s et propose « Ouvrir » dès qu'on a une clé d'agent — l'id de
 *  l'agent, ou à défaut la clé `launching/<ticket>` d'un lancement en fond (la page Agents sait
 *  suivre la préparation puis rebrancher l'onglet sur le vrai agent). */
export function toastAgent(message, cle) {
  const opts = { timeout: 10000 };
  if (cle) opts.action = { label: "Ouvrir", fn: () => { window.location.href = lienAgent(cle); } };
  toast.ok(message, opts);
}

export function lienAgent(agentId) {
  return `/conversations?agent=${enc(agentId)}`;
}
