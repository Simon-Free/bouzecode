// [desc] Bureau, mode « Statut » (SPEC §4.3) : sections À traiter / En cours / À lancer / Archivées, chaque tâche une seule fois avec son chantier en étiquette ; À traiter réunit tâches et points hors tâche, groupés par ce qu'il faut faire (décider, action manuelle, reprendre, vérifier) ; Archivées repliée. [/desc]

import { h } from "../lib/ui.js";
import { state, toutesLesTaches, basculerArchives } from "./store.js";
import { correspond, segmentDe, trier, reconcilier } from "./filtre.js";
import { renderTache, enEdition } from "./tache.js";
import { pointsParTache, pointsHorsTache, lignesHorsTache } from "./attente.js";
import { zoneAjout } from "./sections.js";
import { CATEGORIES, motifDe, categorieDe } from "./attention.js";

const SECTIONS = [
  { key: "a_moi", titre: "À traiter", tone: "warn", vide: "Rien ne t'attend." },
  { key: "en_cours", titre: "En cours", tone: "info", vide: "Aucun agent ne travaille en ce moment." },
  { key: "a_lancer", titre: "À lancer", tone: "neutral", vide: "Rien à lancer : écris une tâche ci-dessous." },
  { key: "archivees", titre: "Archivées", tone: "neutral", vide: "Aucune tâche archivée.", repliable: true },
];

/** Urgence commune aux tâches et aux points hors tâche (même ordre que /api/inbox). */
const URGENCE = { a_repondre: 0, en_echec: 1, a_relire: 2, a_decider: 3 };

const blocs = new Map(); // clé de section -> {el, titre, compte, corps, vide, ajout, bascule}

function bloc(def) {
  let b = blocs.get(def.key);
  if (b) return b;
  const compte = h("span", { class: "count", "data-tone": def.tone });
  const titre = h("h2", { class: "bz-sec__titre" });
  const corps = h("div", { class: "bz-sec__corps" });
  const vide = h("p", { class: "bz-muted bz-sec__vide" });
  const el = h("section", { class: "bz-sec", "data-sec": def.key }, titre, corps);
  b = { el, titre, compte, corps, vide, ajout: null, bascule: null };
  if (def.repliable) {
    b.bascule = h("button", { type: "button", class: "bz-sec__bascule", "aria-expanded": "false" });
    b.bascule.addEventListener("click", () => basculerArchives("statut"));
    titre.append(b.bascule);
  } else {
    titre.append(def.titre, " ", compte);
  }
  if (def.key === "a_lancer") { b.ajout = zoneAjout(null); el.append(b.ajout); }
  blocs.set(def.key, b);
  return b;
}

function tachesParSection() {
  const par = { a_moi: [], en_cours: [], a_lancer: [], archivees: [] };
  for (const t of toutesLesTaches()) {
    if (correspond(t) || enEdition(t.id)) par[segmentDe(t)].push(t);
  }
  return par;
}

const groupes = new Map(); // clé de catégorie -> {el, compte, corps}

/** Un groupe de « À traiter » : titre (ce qu'il faut faire), explication, lignes. */
function groupe(def) {
  let g = groupes.get(def.key);
  if (g) return g;
  const compte = h("span", { class: "count", "data-tone": "warn" });
  const corps = h("div", { class: "bz-sec__corps" });
  g = { compte, corps, el: h("div", { class: "bz-cat", "data-cat": def.key },
    h("h3", { class: "bz-cat__titre" }, def.titre, " ", compte), h("p", { class: "bz-cat__aide" }, def.aide), corps) };
  groupes.set(def.key, g);
  return g;
}

/** « À traiter » : tâches et points hors tâche, groupés par catégorie, par urgence dans chaque groupe. */
function elementsATraiter(taches, points) {
  const hors = pointsHorsTache();
  const lignes = lignesHorsTache(hors);
  const items = [
    ...hors.map((it, i) => ({ cat: categorieDe(it.motif), u: it.urgence ?? 0, el: lignes[i] })),
    ...trier(taches).map((t) => {
      const p = points.get(t.id);
      return { cat: categorieDe(motifDe(t, p)), u: URGENCE[t.statut_ui] ?? 4, el: renderTache(t, { point: p, etiquette: true }) };
    }),
  ].sort((a, b) => a.u - b.u); // tri stable : points d'abord, dans l'ordre du serveur
  const els = [];
  for (const def of CATEGORIES) {
    const dans = items.filter((x) => x.cat === def.key || (!x.cat && def.key === "decider")).map((x) => x.el);
    if (!dans.length) continue;
    const g = groupe(def);
    g.compte.textContent = String(dans.length);
    reconcilier(g.corps, dans);
    els.push(g.el);
  }
  return { els, n: items.length };
}

function elementsDe(def, taches, points, ouverte) {
  if (def.key === "a_moi") return elementsATraiter(taches, points);
  const els = ouverte ? trier(taches).map((t) => renderTache(t, { point: points.get(t.id), etiquette: true })) : [];
  return { els, n: taches.length };
}

function majBascule(def, b, ouverte, n) {
  if (!b.bascule) return;
  b.bascule.textContent = `${ouverte ? "▾" : "▸"} ${def.titre}${n ? ` (${n})` : ""}`;
  b.bascule.setAttribute("aria-expanded", ouverte ? "true" : "false");
}

function remplirSection(def, b, taches, points) {
  const ouverte = !def.repliable || state.archivesOuvertes.has("statut");
  const { els, n } = elementsDe(def, taches, points, ouverte);
  b.compte.textContent = n ? String(n) : "";
  majBascule(def, b, ouverte, n);
  b.corps.hidden = !ouverte;
  b.vide.textContent = state.recherche ? "Aucune tâche ne correspond ici." : def.vide;
  reconcilier(b.corps, els.length || !ouverte ? els : [b.vide]);
  if (b.ajout && b.ajout.majChoix) b.ajout.majChoix();
}

/** Les sections du mode Statut, dans l'ordre, prêtes à être posées dans la liste. */
export function blocsStatut() {
  const par = tachesParSection();
  const points = pointsParTache();
  return SECTIONS.map((def) => {
    const b = bloc(def);
    remplirSection(def, b, par[def.key], points);
    return b.el;
  });
}
