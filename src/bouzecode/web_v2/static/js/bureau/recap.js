// [desc] Rendu du récap d'un passage d'agent (fait / reste à faire / à décider), partagé par « À traiter » et les passages d'une tâche : chaque point laissé dit la tâche qui le porte (statut, lien qui la montre) ou propose « Créer la tâche ». [/desc]

import { h, busy, toast } from "../lib/ui.js";

const MAX_ITEMS = 4;

/** « → tâche créée : Titre · brouillon » (ou « déjà ouverte » quand le point existait déjà). */
const PREFIXES = { creee: "tâche créée", manuelle: "tâche créée", existante: "tâche déjà ouverte", titre: "tâche" };

const minuscule = (s) => (s ? s.charAt(0).toLowerCase() + s.slice(1) : "");

function lienTache(tache, o) {
  const lien = h("a", { class: "bz-suite__lien", href: `#tache-${tache.id}`, "data-tache": tache.id }, tache.titre || "Sans titre");
  lien.addEventListener("click", (e) => { e.preventDefault(); if (o.montrer) o.montrer(tache.id); });
  return h("span", { class: "bz-suite", "data-lien": tache.lien || "" }, `→ ${PREFIXES[tache.lien] || "tâche"} : `, lien,
    tache.libelle_statut ? ` · ${minuscule(tache.libelle_statut)}` : "");
}

function sansTache(texte, decision, o) {
  const bouton = o.creer ? h("button", { type: "button", class: "btn btn--ghost btn--sm bz-suite__creer" }, "Créer la tâche") : null;
  if (bouton) {
    bouton.addEventListener("click", () => busy(bouton, "Création…", async () => {
      try { await o.creer(texte, decision); } catch (e) { toast.err(`Créer la tâche : ${e.message}`); }
    }));
  }
  return h("span", { class: "bz-suite bz-suite--aucune" }, "Aucune tâche créée pour ce point.", bouton ? " " : "", bouton);
}

/** Un point laissé : son texte, puis ce qu'il est devenu (seulement si le serveur le dit). */
function point(texte, suite, decision, o) {
  if (suite === undefined) return h("li", null, texte);
  return h("li", { class: "bz-recap__point" }, h("span", null, texte), suite ? lienTache(suite, o) : sansTache(texte, decision, o));
}

function listeRecap(titre, items, suites, decision, o) {
  if (!items || !items.length) return null;
  const plus = items.length > MAX_ITEMS ? h("li", { class: "bz-muted" }, `… et ${items.length - MAX_ITEMS} autre(s)`) : null;
  return h("div", { class: "bz-recap__bloc" }, h("span", { class: "bz-recap__titre" }, titre),
    h("ul", null, items.slice(0, MAX_ITEMS).map((t, i) => point(t, suites ? suites[i] : undefined, decision, o)), plus));
}

/** Bloc `.bz-recap` d'un récap `{fait, reste, a_decider, resume, suites?}` ; null s'il est vide.
 *  `o.montrer(id)` montre une tâche liée ; `o.creer(libelle, decision)` crée celle d'un point sans tâche. */
export function blocRecap(recap, o = {}) {
  if (!recap) return null;
  const suites = recap.suites || {};
  const blocs = [listeRecap("Fait", recap.fait, null, false, o),
    listeRecap("Reste à faire", recap.reste, suites.reste, false, o),
    listeRecap("À décider", recap.a_decider, suites.a_decider, true, o)].filter(Boolean);
  if (!blocs.length && recap.resume) blocs.push(h("p", { class: "bz-recap__resume" }, recap.resume));
  return blocs.length ? h("div", { class: "bz-recap" }, blocs) : null;
}
