// [desc] Montrer une tâche du Bureau depuis un lien (récap d'un passage) : on la rend visible (recherche, chantier replié, archives), on la déplie, on la surligne et on y défile. [/desc]

import { highlight, toast } from "../lib/ui.js";
import { state, savePrefs, tacheParId, demanderRendu } from "./store.js";
import { correspond, estArchivee } from "./filtre.js";
import { ARCHIVES } from "./chantier.js";

/** Lève ce qui cache `t` dans le mode courant, puis redessine (synchrone). */
function rendreVisible(t) {
  if (state.recherche && !correspond(t)) {
    state.recherche = "";
    const champ = document.getElementById("bz-search");
    if (champ) champ.value = "";
  }
  const chantier = state.mode === "chantier";
  if (estArchivee(t)) state.archivesOuvertes.add(chantier ? (t.macro_id || "__sans") : "statut");
  if (chantier && t.macro_id) {
    state.replies.delete(t.macro_id);
    if (t._chantier && ARCHIVES.includes(t._chantier.etat)) state.archivesOuvertes.add("chantiers");
  }
  savePrefs();
  demanderRendu();
}

/** Déplie et montre la tâche `id` ; false (et le dit) si elle n'est plus sur le Bureau. */
export function revelerTache(id) {
  const t = tacheParId(id);
  if (!t) {
    toast.err("Cette tâche n'est plus sur le Bureau : elle a peut-être été supprimée.");
    return false;
  }
  rendreVisible(t);
  const el = document.querySelector(`.bz-task[data-id="${CSS.escape(id)}"]`);
  if (!el) {
    toast.err(`Impossible d'afficher la tâche « ${t.titre || id} ».`);
    return false;
  }
  const titre = el.querySelector(".bz-task__titre");
  if (titre && titre.getAttribute("aria-expanded") !== "true") titre.click();
  highlight(el);
  if (titre) titre.focus({ preventScroll: true });
  return true;
}
