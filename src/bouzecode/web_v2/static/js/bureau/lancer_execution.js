// [desc] Bloc « Exécution » du dialogue Lancer / Relancer : Local (défaut) ou Rundeck (mode Agent / Tests + commande pytest + navigateur), fichiers non suivis à transmettre (secrets jamais proposés), projets secondaires → champ `execution` (docs/specs/assistant_execution.md). [/desc]
//
// La voie privilégiée reste l'assistant ; ce bloc donne la même option à la main. La liste des
// fichiers vient de GET /api/projects/<slug>/fichiers-non-suivis (service de l'outil `Projets`) :
// on coche d'office ceux que les indices de la tâche désignent, un secret est affiché grisé et
// n'est jamais transmis, un échec de lecture est dit sans bloquer le lancement (R4).

import { h } from "../lib/ui.js";
import * as act from "./actions.js";

const MOTS_MIN = 4;

function radio(nom, valeur, libelle, coche) {
  return h("label", { class: "bz-radio" }, h("input", { type: "radio", name: nom, value: valeur, checked: coche }),
    h("span", null, libelle));
}

// La propriété `checked`, pas le sélecteur `:checked` (que happy-dom lit sur l'attribut initial).
const cochees = (racine, selecteur) => [...racine.querySelectorAll(selecteur)].filter((c) => c.checked);
const coche = (racine, nom) => (cochees(racine, `input[name=${nom}]`)[0] || {}).value;

/** Mots de la tâche (≥ 4 lettres) : ce qui rend un fichier non suivi « proposé ». */
export function indicesDe(texte) {
  return [...new Set(String(texte || "").toLowerCase().split(/[^\p{L}\p{N}_]+/u).filter((m) => m.length >= MOTS_MIN))];
}

function ligneFichier(f, cocher) {
  const secret = f.exclu === "secret";
  const note = secret ? " — secret, jamais transmis" : (f.pertinent && cocher ? " — proposé" : "");
  return h("label", { class: "bz-check", title: secret ? "Les secrets (.env, clés) ne partent jamais avec l'agent." : null },
    h("input", { type: "checkbox", value: f.chemin, "data-role": "fichier", checked: !secret && cocher && f.pertinent,
      disabled: secret }),
    h("span", null, f.chemin, h("span", { class: "bz-muted" }, note)));
}

/**
 * @param {{projets: {slug:string,name?:string}[], principal: () => string, indices?: string, charger?: Function}} o
 * @returns {{el: HTMLElement, charger: () => Promise<void>, valider: () => boolean, valeur: () => object}}
 */
export function champExecution(o) {
  const charger = o.charger || act.fichiersNonSuivis;
  const indices = indicesDe(o.indices);
  const commande = h("input", { class: "input", type: "text", "data-role": "commande",
    placeholder: "tests/web -m playwright -x" });
  const erreurCommande = h("span", { class: "field__error" });
  const fCommande = h("div", { class: "field" }, h("label", null, "Arguments de pytest", commande), erreurCommande);
  const navigateur = h("input", { type: "checkbox", "data-role": "navigateur", checked: true });
  const tests = h("div", { "data-role": "tests", hidden: true }, fCommande,
    h("label", { class: "bz-check" }, navigateur, h("span", null, "Installer le navigateur (Chromium) avant les tests")));
  const modes = h("div", { class: "bz-launch__modes", "data-role": "modes-distants" },
    radio("bz-mode-distant", "agent", "Agent — un agent bouzecode travaille sur la VM", true),
    radio("bz-mode-distant", "tests", "Tests seulement — la VM joue pytest et rend JUnit + captures", false));
  const distant = h("div", { "data-role": "rundeck", hidden: true }, modes, tests);
  const etatFichiers = h("p", { class: "field__hint", "data-role": "fichiers-etat", "aria-live": "polite" });
  const listeFichiers = h("div", { class: "bz-launch__fichiers", "data-role": "fichiers" });
  const listeProjets = h("div", { class: "bz-launch__fichiers", "data-role": "projets-sup" });
  const el = h("fieldset", { class: "bz-launch__modes bz-launch__exec", "data-role": "execution" },
    h("legend", { class: "field__label" }, "Où tourne l'agent ?"),
    radio("bz-cible", "local", "Sur ce poste (local)", true),
    radio("bz-cible", "rundeck", "Sur Rundeck — VM Linux de recette", false),
    distant,
    h("details", { class: "bz-launch__plus" }, h("summary", null, "Fichiers non suivis à transmettre"), etatFichiers, listeFichiers),
    h("details", { class: "bz-launch__plus" }, h("summary", null, "Projets secondaires"), listeProjets));

  function projetsSecondaires() {
    listeProjets.replaceChildren(...o.projets.filter((p) => p.slug !== o.principal()).map((p) =>
      h("label", { class: "bz-check" }, h("input", { type: "checkbox", value: p.slug, "data-role": "projet" }),
        h("span", null, p.name || p.slug))));
  }

  function sync() {
    const surRundeck = coche(el, "bz-cible") === "rundeck";
    distant.hidden = !surRundeck;
    tests.hidden = !(surRundeck && coche(el, "bz-mode-distant") === "tests");
  }
  el.addEventListener("change", sync);

  let seq = 0;
  async function chargerFichiers() {
    projetsSecondaires();
    const slug = o.principal();
    const moi = ++seq;
    listeFichiers.replaceChildren();
    if (!slug) { etatFichiers.textContent = "Choisis d'abord le dépôt."; return; }
    etatFichiers.textContent = "Lecture des fichiers non suivis…";
    listeFichiers.setAttribute("aria-busy", "true");
    try {
      const r = await charger(slug, indices.join(" "));
      if (moi !== seq) return;
      const visibles = (r.non_suivis || []).filter((f) => !f.exclu || f.exclu === "secret");
      listeFichiers.replaceChildren(...visibles.map((f) => ligneFichier(f, indices.length > 0)));
      const exclus = (r.non_suivis || []).length - visibles.length;
      etatFichiers.textContent = visibles.length
        ? `${visibles.length} fichier(s)${exclus ? ` · ${exclus} exclu(s) (binaires, trop gros, temp_*)` : ""}${r.tronque ? " · liste tronquée" : ""}`
        : "Aucun fichier non suivi à transmettre.";
    } catch (e) {
      if (moi === seq) etatFichiers.textContent = `Fichiers non suivis indisponibles : ${e.message}`;
    } finally {
      if (moi === seq) listeFichiers.removeAttribute("aria-busy");
    }
  }

  function valider() {
    erreurCommande.textContent = "";
    fCommande.dataset.invalid = "false";
    if (!tests.hidden && !commande.value.trim()) {
      erreurCommande.textContent = "Donne les arguments de pytest (ex. tests/web -x).";
      fCommande.dataset.invalid = "true";
      commande.focus();
      return false;
    }
    return true;
  }

  function valeur() {
    const principal = o.principal();
    const cible = coche(el, "bz-cible") || "local";
    const fichiers = cochees(listeFichiers, "input[data-role=fichier]").map((c) => c.value);
    const sup = cochees(listeProjets, "input[data-role=projet]").map((c) => c.value);
    const execution = { cible, projets: [principal, ...sup], fichiers_non_suivis: fichiers.length ? { [principal]: fichiers } : {} };
    if (cible === "rundeck") {
      execution.mode = coche(el, "bz-mode-distant") || "agent";
      if (execution.mode === "tests") Object.assign(execution, { commande: commande.value.trim(), navigateur: navigateur.checked });
    }
    return execution;
  }

  return { el, charger: chargerFichiers, valider, valeur };
}

/** Lancement ordinaire (local, un seul dépôt, aucun fichier) : rien à envoyer au PREMIER lancement. */
export function estOrdinaire(execution) {
  return execution.cible === "local" && execution.projets.length === 1
    && !Object.values(execution.fichiers_non_suivis).some((l) => l.length);
}

/** Ce que le passage / le toast disent d'un lancement Rundeck : lien et fichiers NON transmis. */
export function fichiersRefuses(distant) {
  return Object.entries((distant && distant.fichiers_refuses) || {})
    .flatMap(([slug, liste]) => (liste || []).map((f) => `${slug}/${f.chemin || f}${f.raison ? ` (${f.raison})` : ""}`));
}
