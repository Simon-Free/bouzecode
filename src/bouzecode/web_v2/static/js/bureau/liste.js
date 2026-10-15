// [desc] Liste du Bureau (SPEC §4.3) : bascule entre les deux modes de tri (Statut | Chantier), recherche commune, états sans données / erreur / vide ; rendu différé pendant un menu ouvert ou un glisser-déposer. [/desc]
//
// Une seule vue à la fois, chaque tâche UNE fois. Rendu RÉCONCILIÉ : sections et tâches gardent
// leur nœud DOM d'un rendu à l'autre (filtre.js::reconcilier) ; une tâche en cours d'édition ne
// disparaît jamais sous les yeux (R8).

import { skeleton, failed, empty } from "../lib/ui.js";
import { state, toutesLesTaches, choisirMode, MODES } from "./store.js";
import { correspond, reconcilier } from "./filtre.js";
import { pointsHorsTache } from "./attente.js";
import { blocsStatut } from "./vue_statut.js";
import { blocsChantier } from "./vue_chantier.js";
import { glisserEnCours } from "./glisser.js";
import * as act from "./actions.js";
import { oublierDisparues } from "./tache.js";

// ---------------------------------------------------------------- sélecteur de mode

export function renderMode() {
  const barre = document.getElementById("bz-mode");
  if (barre) {
    for (const b of barre.querySelectorAll("[data-mode]")) {
      b.setAttribute("aria-pressed", b.dataset.mode === state.mode ? "true" : "false");
    }
  }
  const nouveau = document.getElementById("chantier-nouveau");
  if (nouveau) nouveau.hidden = state.mode !== "chantier";
}

function cablerMode(barre) {
  barre.addEventListener("click", (e) => {
    const b = e.target.closest("[data-mode]");
    if (b) choisirMode(b.dataset.mode);
  });
  // Flèches gauche / droite : passer d'un mode à l'autre au clavier.
  barre.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const i = MODES.findIndex((m) => m.key === state.mode);
    const suivant = MODES[(i + (e.key === "ArrowRight" ? 1 : MODES.length - 1)) % MODES.length].key;
    e.preventDefault();
    choisirMode(suivant);
    const b = barre.querySelector(`[data-mode="${suivant}"]`);
    if (b) b.focus();
  });
}

// ---------------------------------------------------------------- rendu

/** Rien de chargé encore : erreur (avec Réessayer) ou squelette. Renvoie true si c'est le cas. */
function rendreSansDonnees(racine, erreur) {
  if (state.lignes) return false;
  if (erreur) failed(racine, erreur, () => act.rafraichir(), { title: "Impossible de charger tes tâches." });
  else skeleton(racine, 6);
  return true;
}

/** Un menu ⋯ ouvert dans la liste, ou un glisser-déposer en cours ? Le rendu reconstruit les
 *  en-têtes de chantier et déplace des tâches : le menu ou la cible disparaîtrait sous le
 *  pointeur (R8). Les gestes ferment le menu AVANT d'agir, et la fin d'un glisser redemande un
 *  rendu : seuls les rafraîchissements de fond sont différés. */
let renduDiffere = null;
const occupee = (racine) => !!racine.querySelector(".menu__list") || glisserEnCours();

function differerSiMenuOuvert(racine, erreur) {
  if (!occupee(racine)) return false;
  if (!renduDiffere) {
    renduDiffere = setInterval(() => {
      if (occupee(racine)) return;
      clearInterval(renduDiffere);
      renduDiffere = null;
      rendreListe(erreur);
    }, 300);
  }
  return true;
}

/** Une recherche qui ne trouve rien nulle part : un seul message, pas des sections vides. */
function rechercheSansResultat() {
  return !!state.recherche && !toutesLesTaches().some(correspond) && !pointsHorsTache().length;
}

export function rendreListe(erreur) {
  renderMode();
  const racine = document.getElementById("lignes-liste");
  if (!racine || rendreSansDonnees(racine, erreur)) return;
  if (differerSiMenuOuvert(racine, erreur)) return;
  racine.removeAttribute("aria-busy");
  racine.dataset.mode = state.mode;
  if (rechercheSansResultat()) {
    for (const el of [...racine.children]) if (!el.classList.contains("empty")) el.remove();
    if (!racine.querySelector(":scope > .empty")) {
      empty(racine, { title: `Aucune tâche pour « ${state.recherche} ».`, text: "La recherche porte sur le titre et le brief." });
    }
    return;
  }
  const vide = racine.querySelector(":scope > .empty");
  if (vide) vide.remove();
  reconcilier(racine, state.mode === "chantier" ? blocsChantier() : blocsStatut());
  oublierDisparues(new Set(toutesLesTaches().map((t) => t.id)));
}

// ---------------------------------------------------------------- câblage

function cablerRecherche(rech) {
  let t = null;
  const rechercher = (v) => { state.recherche = v; rendreListe(); };
  rech.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => rechercher(rech.value.trim()), 120); });
  rech.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { rech.value = ""; rechercher(""); rech.blur(); }
  });
  // « / » donne le focus à la recherche, sauf quand on écrit déjà quelque part.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const a = document.activeElement;
    if (a && (["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName) || a.isContentEditable)) return;
    e.preventDefault();
    rech.focus();
  });
}

export function wireListe() {
  const barre = document.getElementById("bz-mode");
  if (barre) cablerMode(barre);
  const rech = document.getElementById("bz-search");
  if (rech) cablerRecherche(rech);
  renderMode();
}
