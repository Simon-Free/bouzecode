// [desc] Corps d'une tâche dépliée : UN champ, le brief (sa 1re ligne est le libellé dans la liste), enregistré automatiquement ; liste Dépôt ; zones question / gestes / passages. [/desc]
//
// Pas de titre à part, pas de bouton Enregistrer (demande du 2026-09-24) : le brief s'enregistre
// seul à la frappe, à la perte de focus et avant de lancer (autosave.js). Le chantier se change
// par glisser-déposer ou par « Déplacer vers… » dans le menu ⋯ (deplacer.js).

import { h, toast, highlight, api } from "../lib/ui.js";
import { openReposDialog } from "../projects_admin.js";
import { state, nomProjet } from "./store.js";
import { autosave } from "./autosave.js";
import * as act from "./actions.js";
import { zoneRendu } from "./tache_rendu.js";

const premiereLigne = (texte) => (String(texte || "").split("\n").map((l) => l.trim().replace(/^#+\s*/, "")).find(Boolean) || "");
/** Le titre est-il la 1re ligne du brief, ou sa coupe ? Le serveur (`micros.titre_depuis_corps`)
 *  coupe une 1re ligne trop longue à sa 1re phrase ou au mot avec « … » : c'en est le DÉBUT. */
const titreEnTete = (titre, corps) => {
  const ligne = premiereLigne(corps);
  const court = titre.replace(/[….\s]+$/u, "");
  return titre === ligne || (!!court && ligne.startsWith(court));
};

/** Le brief montré à l'écran. Une tâche écrite par un agent peut avoir un titre qui n'est pas la
 *  1re ligne de son corps : on le met en tête, pour que le libellé reste le même après édition. */
export function briefAffiche(t) {
  const titre = (t.titre || "").trim();
  const corps = t.corps || "";
  if (!titre || titreEnTete(titre, corps)) return corps;
  return corps ? `${titre}\n\n${corps}` : titre;
}

function editeur(rec) {
  const brief = h("textarea", { class: "textarea bz-ed__brief", rows: "7", "aria-label": "Brief de la tâche",
    placeholder: "La 1re ligne sert de titre. Puis le contexte, les pièges, les fichiers, le critère de réussite… (markdown)" });
  brief.value = briefAffiche(rec.t);
  const etat = h("span", { class: "bz-ed__etat", role: "status", "aria-live": "polite" });
  const auto = autosave(brief, etat, (valeur) => act.modifierTache(rec.id, { corps: valeur }), (r) => {
    if (!r || !r.micro) return;
    rec.t.titre = r.micro.titre;
    rec.t.corps = r.micro.corps;
    if (rec.titre.textContent !== (r.micro.titre || "")) rec.titre.textContent = r.micro.titre || "Sans titre";
  });
  const form = h("div", { class: "bz-ed" },
    h("div", { class: "field" }, h("div", { class: "bz-ed__tete" }, h("label", null, "Brief"), etat), brief));
  return { form, brief, auto };
}

// ---------------------------------------------------------------- dépôt

async function changerDepot(rec, select) {
  select.disabled = true;
  select.setAttribute("aria-busy", "true");
  try {
    await act.modifierTache(rec.id, { projet_slug: select.value });
    toast.ok(select.value ? `Dépôt : ${nomProjet(select.value)}.` : "Dépôt retiré.");
    await act.rafraichir();
    requestAnimationFrame(() => highlight(rec.el));
  } catch (e) {
    toast.err(`Modification impossible : ${e.message}`);
    remplirSelects(rec, true);
  } finally {
    select.disabled = false;
    select.removeAttribute("aria-busy");
  }
}

function remplirDepot(select, t) {
  const sig = JSON.stringify([state.projets.map((p) => p.slug), t.projet_slug, t.projet_defaut]);
  if (select.dataset.sig === sig) return;
  select.dataset.sig = sig;
  const vide = t.projet_defaut && !t.projet_slug
    ? `Par défaut du chantier (${nomProjet(t.projet_defaut)})` : "— aucun (à choisir au lancement)";
  select.replaceChildren(h("option", { value: "" }, vide),
    ...state.projets.map((p) => h("option", { value: p.slug }, p.name || p.slug)));
  select.value = t.projet_slug || "";
}

/** Met la liste Dépôt à jour, sauf si elle a le focus (sauf `force`). */
export function remplirSelects(rec, force) {
  if (force || document.activeElement !== rec.selects.depot) remplirDepot(rec.selects.depot, rec.t);
}

function reglages(rec) {
  const depot = h("select", { class: "select", "aria-label": "Dépôt" });
  rec.selects = { depot };
  depot.addEventListener("change", () => changerDepot(rec, depot));
  const ajouter = h("button", { type: "button", class: "btn btn--ghost btn--sm", "data-role": "ajouter-depot",
    title: "Enregistrer un nouveau dépôt et le choisir pour cette tâche" }, "+ dépôt");
  ajouter.addEventListener("click", () => openReposDialog({
    onChange: async () => {
      const res = await api("GET", "/api/projects");
      if (res && Array.isArray(res.projects)) state.projets = res.projects;
    },
    onAdded: (slug) => {
      if (![...depot.options].some((o) => o.value === slug)) {
        const p = state.projets.find((x) => x.slug === slug);
        depot.append(h("option", { value: slug }, (p && (p.name || p.slug)) || slug));
      }
      depot.value = slug;
      depot.dispatchEvent(new Event("change"));
    },
  }));
  return h("div", { class: "bz-ed__reglages" },
    h("div", { class: "field" }, h("label", null, "Dépôt"), h("div", { class: "bz-ed__depot" }, depot, ajouter)));
}

/** Construit (une fois) le corps de la tâche dépliée et l'accroche à `rec.el`. */
export function construireCorps(rec) {
  const ed = editeur(rec);
  rec.editeur = { brief: ed.brief, auto: ed.auto };
  rec.sauver = () => ed.auto.vider();
  rec.zonePassages = h("div", { class: "bz-passages" });
  rec.zoneActions = h("div", { class: "btn-row bz-task__actions" });
  rec.zoneClassements = h("div", { class: "bz-classements" });
  // Ce qui t'attend est dans la bande (au-dessus, toujours visible) ; ici les gestes du statut,
  // pourquoi elle a été classée, le brief, le dépôt, puis l'historique.
  rec.zoneRendu = zoneRendu(rec);
  rec.corps = h("div", { class: "bz-task__body" }, rec.zoneActions, rec.zoneClassements, ed.form, reglages(rec),
    rec.zoneRendu, rec.zonePassages);
  rec.el.appendChild(rec.corps);
}

/** Le poll ne touche au brief que si l'utilisateur n'y écrit pas (R8). */
export function majEditeur(rec) {
  if (rec.editeur) rec.editeur.auto.depuisServeur(briefAffiche(rec.t), state.lueNo);
}

/** Une tâche dont le brief n'est pas encore enregistré (ou a le focus) ne doit pas disparaître. */
export function editionEnCours(rec) {
  return !!(rec.editeur && (rec.editeur.auto.enAttente() || rec.el.contains(document.activeElement)));
}
