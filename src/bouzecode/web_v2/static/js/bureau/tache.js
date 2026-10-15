// [desc] Une tâche du Bureau : ligne repliée légère (état en un mot, titre, une ligne secondaire, action principale au survol), bande « ce qui t'attend » toujours visible (question, gestes attendus), poignée de déplacement, dépliage, et mise à jour en place des zones vivantes. [/desc]
//
// Le DOM d'une tâche est PERSISTANT (registre par id) : le poll met à jour la ligne et les
// sections vivantes EN PLACE, et ne touche jamais aux champs de l'éditeur quand ils sont
// modifiés ou ont le focus (R8). L'éditeur est dans tache_editeur.js, les gestes dans
// tache_gestes.js, l'historique dans passages.js. Repliée, une ligne ne montre que l'essentiel :
// dépôt, date, passages et chantier sont dans l'infobulle et dans le détail.

import { api, h, hhmm, relTime, toast } from "../lib/ui.js";
import { taskStatus, badge } from "../lib/states.js";
import { parseInstant } from "../time_format.js";
import { state, savePrefs, nomProjet } from "./store.js";
import { blocQuestion, signatureQuestion } from "./question.js";
import { ouvrirLancement } from "./lancer.js";
import { construireCorps, remplirSelects, majEditeur, editionEnCours } from "./tache_editeur.js";
import { gestes, gestesAttente } from "./tache_gestes.js";
import { rendrePassages, signaturePassages } from "./passages.js";
import { resumePoint } from "./attente.js";
import { blocPlan } from "./inbox_carte.js";
import { MOTIFS, motifDe, badgeMotif } from "./attention.js";
import { rendreGlissable } from "./glisser.js";
import { deplacerVers, deplacerTache } from "./deplacer.js";
import * as act from "./actions.js";
import { texteClassement, texteHistorique } from "./classement.js";

export const registre = new Map(); // id -> rec

/** Retire du registre les tâches que le serveur ne sert plus (supprimées, déplacées hors de la
 *  vue) : leur élément et leur éditeur restaient en mémoire toute la session. Une tâche encore
 *  dans la page ou en cours d'édition est gardée. */
export function oublierDisparues(ids) {
  for (const [id, rec] of registre) {
    if (ids.has(id) || (rec.el && rec.el.isConnected) || editionEnCours(rec)) continue;
    registre.delete(id);
  }
}


// ---------------------------------------------------------------- ligne repliée

async function lancer(rec, bouton) {
  if (rec.editeur && !rec.editeur.brief.value.trim()) {
    deplier(rec, true, ".bz-ed__brief");
    toast.err("Écris d'abord le brief de la tâche.");
    return;
  }
  await ouvrirLancement(rec.t, { mode: "lancer", avant: rec.sauver });
  if (bouton && bouton.isConnected) bouton.focus();
}

/** L'action de la ligne, au survol — seulement pour une tâche qui n'attend rien de toi : sinon
 *  les gestes attendus sont déjà visibles dans sa bande. */
function actionPrincipale(rec, t) {
  const p = (t.passages || [])[0];
  if (rec.motif) return null;
  if (t.statut_ui === "brouillon") return { label: "Lancer", fn: (b) => lancer(rec, b) };
  if (t.statut_ui === "en_cours" && p && p.agent_id) return { label: "Voir l'agent", href: act.lienAgent(p.agent_id) };
  return null;
}

/** UNE ligne secondaire : pourquoi la tâche t'attend (la question elle-même est dans la bande),
 *  sinon ce que fait l'agent. */
function ligneSecondaire(rec, t) {
  if (rec.motif === "question" || rec.motif === "plan") return "";
  if (rec.motif === "point") return MOTIFS.point.aide;
  if (rec.motif === "livraison") return (rec.attente && resumePoint(rec.attente)) || MOTIFS[rec.motif].aide;
  if (rec.motif) return t.raison_echec || MOTIFS[rec.motif].aide;
  if (t.classement) return texteClassement(t.classement);
  if (t.archive_auto) return t.archive_auto.texte || "Archivée automatiquement.";
  return t.activite || "";
}

/** Statuts où une précision transmise à l'agent compte encore (il travaille, attend, ou vient de rendre). */
const STATUTS_TRANSMIS = new Set(["en_cours", "a_repondre", "a_relire"]);
const LECTURE = { lue: "lue par l'agent", en_attente: "pas encore lue par l'agent", non_lue: "non lue (agent arrêté)" };

/** La dernière précision transmise à l'agent de la tâche : quand, et s'il l'a lue (SPEC §4.5). */
export function derniereTransmission(t) {
  if (!STATUTS_TRANSMIS.has(t.statut_ui)) return null;
  const precisions = t.precisions || [];
  for (let i = precisions.length - 1; i >= 0; i -= 1) {
    const tr = (precisions[i].transmissions || [])[0];
    if (tr) return { quand: precisions[i].created_at, lecture: tr.statut, mode: tr.mode };
  }
  return null;
}

function texteTransmission(d) {
  if (!d) return "";
  const quand = parseInstant(d.quand);
  const heure = quand ? hhmm(quand) : "";
  const verbe = d.mode === "interruption" ? "transmise (tour interrompu)" : "transmise";
  return `✎ Précision ${verbe}${heure ? ` à ${heure}` : ""} — ${LECTURE[d.lecture] || d.lecture}`;
}

function infobulle(t) {
  const depot = t.projet_slug || t.projet_defaut;
  const n = (t.passages || []).length;
  return [t.libelle_statut, t._chantier ? t._chantier.titre : "Sans chantier", depot && `dépôt ${nomProjet(depot)}`,
    n ? `${n} passage${n > 1 ? "s" : ""}` : "", relTime(t.updated_at || t.created_at)].filter(Boolean).join(" · ");
}

function construire(t) {
  const rec = { id: t.id, t, ouvert: false, corps: null, editeur: null, sigPassages: "", sigQuestion: "", sigActions: "", sigGestes: "" };
  rec.lancer = (b) => lancer(rec, b);
  rec.deplier = (sel) => deplier(rec, true, sel);
  const el = h("article", { class: "bz-task", "data-id": t.id });
  const poignee = h("button", { type: "button", class: "bz-grip", "aria-label": "Déplacer la tâche vers un autre chantier",
    title: "Glisser vers un autre chantier (Échap annule) — ou clic / Entrée : « Déplacer vers… »" }, "⠿");
  // La ligne entière déplie à la souris ; le TITRE est le vrai bouton (clavier, lecteur d'écran) :
  // pas d'éléments interactifs imbriqués dans un role=button.
  const ligne = h("div", { class: "bz-task__row" });
  const titre = h("button", { type: "button", class: "bz-task__titre", "aria-expanded": "false" });
  const meta = h("span", { class: "bz-task__meta" });
  const transmis = h("span", { class: "bz-task__transmis", hidden: true });
  const chantier = h("span", { class: "bz-task__chantier", hidden: true });
  const slotBadge = h("span", { class: "bz-task__badge" });
  const slotAction = h("span", { class: "bz-task__action" });
  ligne.append(poignee, slotBadge, h("span", { class: "bz-task__txt" }, titre, meta, transmis), chantier, slotAction);
  // Ce qui t'attend : TOUJOURS visible, repliée ou non — l'action attendue est sur la carte.
  const zoneQuestion = h("div", { class: "bz-task__question" });
  const zoneGestes = h("div", { class: "btn-row bz-attente__gestes" });
  //  Décision laissée par un agent clôturé : sa réponse finale, pour décider en connaissance de cause.
  const zoneSource = h("div", { class: "bz-task__source" });
  const bande = h("div", { class: "bz-task__attente", hidden: true }, zoneSource, zoneQuestion, zoneGestes);
  el.append(ligne, bande);
  Object.assign(rec, { el, ligne, titre, meta, transmis, chantier, slotBadge, slotAction, poignee, bande, zoneSource, zoneQuestion, zoneGestes });
  ligne.addEventListener("click", (e) => {
    if (e.target.closest(".bz-task__action, .bz-grip")) return;
    deplier(rec, !rec.ouvert);
  });
  rendreGlissable(poignee, { type: "tache", id: t.id, source: el, libelle: () => rec.t.titre || "Tâche",
    origine: () => rec.t.macro_id || "", surClic: () => deplacerVers(rec), deposer: (cible) => deplacerTache(rec, cible.id) });
  registre.set(t.id, rec);
  return rec;
}

function majTexte(el, texte) {
  if (el.textContent !== texte) el.textContent = texte;
  el.hidden = !texte;
}

function majLigne(rec, t, etiquette) {
  const st = taskStatus(t.statut_ui || t);
  rec.el.dataset.statut = st.key;
  rec.el.dataset.motif = rec.motif;
  rec.el.classList.toggle("is-attention", !!rec.motif);
  const mot = (t.classement && t.classement.libelle) || st.label;
  //  En mode Statut, la section « À lancer » dit déjà le statut : ses lignes ne répètent que
  //  l'icône (le mot reste en infobulle et pour les lecteurs d'écran).
  const compact = etiquette && !rec.motif && st.key === "brouillon" && !t.classement;
  rec.slotBadge.replaceChildren(rec.motif ? badgeMotif(rec.motif)
    : badge({ ...st, label: mot }, { title: t.libelle_statut || st.label, compact }));
  majTexte(rec.titre, t.titre || "Sans titre");
  rec.titre.hidden = false;
  majTexte(rec.meta, ligneSecondaire(rec, t));
  const transmission = derniereTransmission(t);
  majTexte(rec.transmis, texteTransmission(transmission));
  rec.transmis.dataset.lecture = transmission ? transmission.lecture : "";
  majTexte(rec.chantier, etiquette ? ((t._chantier && t._chantier.titre) || "Sans chantier") : "");
  rec.ligne.title = infobulle(t);
  return st;
}

/** L'action principale de la ligne ; jamais remplacée pendant qu'elle est en cours. */
function majActionPrincipale(rec, t, st) {
  const a = actionPrincipale(rec, t);
  const sig = a ? a.label + (a.href || "") : "";
  if (rec.sigAction === sig || rec.slotAction.querySelector("[aria-busy='true']")) return;
  rec.sigAction = sig;
  if (!a) { rec.slotAction.replaceChildren(); return; }
  if (a.href) { rec.slotAction.replaceChildren(h("a", { class: "btn btn--sm", href: a.href }, a.label)); return; }
  const btn = h("button", { type: "button", class: `btn btn--sm${st.key === "brouillon" ? " btn--primary" : ""}` }, a.label);
  btn.addEventListener("click", (e) => { e.stopPropagation(); a.fn(btn); });
  rec.slotAction.replaceChildren(btn);
}

/** Crée ou met à jour la tâche `t` ; renvoie son élément.
 *  `point` : ce qui attend un geste sur cette tâche (/api/inbox) ; `etiquette` : rappeler son chantier. */
export function renderTache(t, { point = null, etiquette = false } = {}) {
  const rec = registre.get(t.id) || construire(t);
  rec.t = t;
  rec.attente = point;
  rec.motif = motifDe(t, point);
  majActionPrincipale(rec, t, majLigne(rec, t, etiquette));
  majAttente(rec);
  if (state.deplies.has(t.id) && !rec.ouvert) deplier(rec, true, null, false);
  if (rec.ouvert) majCorps(rec);
  return rec.el;
}

// ---------------------------------------------------------------- dépliage

export function deplier(rec, ouvrir, focusSel, memoriser = true) {
  rec.ouvert = ouvrir;
  rec.titre.setAttribute("aria-expanded", ouvrir ? "true" : "false");
  rec.el.classList.toggle("is-open", ouvrir);
  // Dépliée, la tâche montre ses gestes dans le détail : l'action de ligne en doublon disparaît
  // (le pilote a vu deux « Lancer » à la fois — le CSS seul ne suffisait pas sur écran tactile).
  rec.slotAction.hidden = ouvrir;
  if (memoriser) {
    if (ouvrir) state.deplies.add(rec.id); else state.deplies.delete(rec.id);
    savePrefs();
  }
  if (!ouvrir) { if (rec.corps) rec.corps.hidden = true; return; }
  if (!rec.corps) construireCorps(rec);
  rec.corps.hidden = false;
  chargerDetail(rec);  // brief, précisions, tickets et TOUS les passages : hors payload de liste
  majCorps(rec);
  const cible = focusSel && rec.corps.querySelector(focusSel);
  if (cible) cible.focus();
}

// ---------------------------------------------------------------- zones vivantes

/** La question à poser dans le détail : celle du point d'attente (avec son plan), sinon celle de la tâche. */
function questionDe(rec) {
  const p = rec.attente;
  if (p && (p.type === "question" || p.type === "plan")) return { q: p.question || {}, agent: p.agent_id, plan: p.type === "plan" };
  const t = rec.t;
  if (t.statut_ui !== "a_repondre" || !t.question) return null;
  const passage = (t.passages || []).find((x) => x.question);
  return { q: t.question, agent: (passage && passage.agent_id) || t.question.agent_id, plan: false };
}

function blocReponse(d) {
  return [d.plan ? blocPlan(d.q.plan) : null, blocQuestion(d.q, async (texte) => {
    await act.repondreAgent(d.agent, texte);
    window.dispatchEvent(new CustomEvent("ui:counts-changed"));
    setTimeout(() => act.rafraichir(), 1500);
  })].filter(Boolean);
}

function majQuestion(rec) {
  const d = questionDe(rec);
  const sig = d ? signatureQuestion(d.q) + (d.plan ? d.q.plan || "" : "") : "";
  const bloc = rec.zoneQuestion.querySelector(".bz-q");
  //  Réponse EN VOL : on ne redessine pas. Réponse ENVOYÉE (« Réponse envoyée… ») : gardée tant que
  //  le serveur sert la même question, mais une AUTRE question du même agent la remplace — sinon la
  //  2e question n'apparaissait jamais.
  //  (Un bloc répondu reste marqué `locked` : c'est `done` qui dit la réponse partie.)
  const envoyee = !!bloc && bloc.dataset.done === "true";
  const enVol = !!bloc && !envoyee && bloc.dataset.locked === "true";
  if (sig === rec.sigQuestion || enVol || (envoyee && !sig)) return;
  rec.sigQuestion = sig;
  rec.zoneQuestion.replaceChildren(...(d ? blocReponse(d) : []));
}

/** Redessine `zone` si `sig` a changé — jamais pendant qu'un de ses gestes est en cours. */
function majZone(rec, cle, zone, sig, contenu) {
  if (sig === rec[cle] || zone.querySelector("[aria-busy='true']")) return;
  rec[cle] = sig;
  zone.replaceChildren(...contenu());
}

/** Réponse finale de l'agent qui a laissé la décision : aperçu court, texte complet dépliable,
 *  lien vers sa conversation. Rien si la tâche n'en a pas (créée à la main). */
export function blocDecisionSource(src) {
  if (!src || !src.ticket_id) return [];
  const qui = src.agent_id ? `l'agent ${src.agent_id}` : `le ticket ${src.ticket_id}`;
  const apercu = String(src.resume || "").split("\n").filter((l) => l.trim()).slice(0, 3).join("\n");
  const complet = h("div", { class: "bz-source__rapport md" });
  if (src.rapport_html) complet.innerHTML = src.rapport_html;  // rendu sûr côté serveur (_rapport_html)
  else complet.textContent = src.resume || "";
  return [h("details", { class: "bz-source" },
    h("summary", {}, `Réponse finale de ${qui}`, src.titre ? ` — ${src.titre}` : ""),
    apercu ? h("p", { class: "bz-source__apercu" }, apercu) : null,
    complet,
    src.agent_id ? h("a", { class: "bz-source__lien", href: act.lienAgent(src.agent_id) }, "Ouvrir la conversation de l'agent") : null,
  )];
}

/** La bande « ce qui t'attend » : la question (ou le plan) et les gestes attendus. */
function majAttente(rec) {
  const t = rec.t;
  rec.bande.hidden = !rec.motif;
  const src = rec.motif === "point" ? t.decision_source : null;
  majZone(rec, "sigSource", rec.zoneSource, JSON.stringify(src || null), () => blocDecisionSource(src));
  if (!rec.motif) { rec.sigGestes = ""; rec.zoneGestes.replaceChildren(); majQuestion(rec); return; }
  majQuestion(rec);
  const p = (t.passages || [])[0] || {};
  majZone(rec, "sigGestes", rec.zoneGestes, JSON.stringify([rec.motif, t.joignable, t.agent_actif, p.agent_id, p.integrable, p.integre]),
    () => gestesAttente(rec, rec.motif));
}

//  Le payload de /api/lignes est ALLÉGÉ : les passages complets (récap + rapport rendu)
//  et le brief pesaient 1,7 Mo sur 2,5 Mo, RETÉLÉCHARGÉS toutes les 5-15 s par le poller.
//  Le détail d'une tâche est donc chargé À LA DEMANDE, au dépli, via /api/lignes/<id>, et
//  mémorisé ici : chaque poll rend une ligne LÉGÈRE (`_leger`), on lui réapplique le détail.
//  Une ligne servie COMPLÈTE par le serveur (tâche dépliée, cf. ?detail=) prime et
//  rafraîchit ce cache : c'est ce qui garde les passages vivants pendant qu'on regarde.
const details = new Map();
const detailsEnVol = new Set();

function chargerDetail(rec) {
  //  Ligne servie COMPLÈTE (dépliée côté serveur, ou hors poll) : rien à compléter.
  if (!rec.t || !rec.t._leger) return;
  const id = String(rec.id);
  if (details.has(id) || detailsEnVol.has(id)) return;
  detailsEnVol.add(id);
  api("GET", `/api/lignes/${encodeURIComponent(id)}`)
    .then((data) => {
      const ligne = data && data.ligne;
      if (!ligne) return;
      details.set(id, ligne);
      if (rec.t && String(rec.t.id) === id) Object.assign(rec.t, ligne);
      if (rec.ouvert && rec.corps) majCorps(rec);
    })
    //  Détail facultatif : en cas d'échec la ligne légère reste affichée, le dépli suivant réessaie.
    .catch(() => null)
    .finally(() => { detailsEnVol.delete(id); });
}

/** Les ids dont le détail est affiché : le poll les demande COMPLETS (`?detail=`). */
export function idsAvecDetail() {
  return [...details.keys()];
}

function majCorps(rec) {
  const id = String(rec.id);
  if (rec.t && rec.t._leger) {
    const enrichi = details.get(id);
    if (enrichi) Object.assign(rec.t, enrichi);
  } else if (rec.t && details.has(id)) {
    details.set(id, rec.t);  // servie complète par le poll : elle devient la référence
  }
  const t = rec.t;
  majEditeur(rec);
  remplirSelects(rec, false);
  majZone(rec, "sigActions", rec.zoneActions,
    JSON.stringify([t.statut_ui, rec.motif, t.agent_actif, (t.passages || [])[0]?.agent_id]), () => gestes(rec, rec.motif));
  majZone(rec, "sigClassements", rec.zoneClassements, JSON.stringify(t.classements || []), () => historique(t));
  majZone(rec, "sigPassages", rec.zonePassages, signaturePassages(t), () => rendrePassages(t));
}

/** Pourquoi la tâche a été classée, et ses classements rouverts (le plus récent en tête). */
function historique(t) {
  const entrees = [...(t.classements || [])].reverse();
  if (!entrees.length) return [];
  return [h("h3", { class: "bz-classements__titre" }, "Classements"),
    h("ul", { class: "bz-classements__liste" }, ...entrees.map((c) =>
      h("li", { class: "bz-classement", "data-motif": c.motif, "data-rouvert": c.rouvert_at ? "true" : "false" },
        texteHistorique(c))))];
}

/** Une tâche en cours d'édition ne doit pas disparaître sous les yeux (R8). */
export function enEdition(id) {
  const rec = registre.get(id);
  return !!(rec && rec.ouvert && editionEnCours(rec));
}
