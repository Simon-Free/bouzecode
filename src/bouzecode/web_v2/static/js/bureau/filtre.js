// [desc] Outils de liste du Bureau partagés par les deux modes de tri : recherche (sans accents ni casse), segment et rang d'urgence d'une tâche, tri, réconciliation du DOM. [/desc]

import { TASK_STATUSES } from "../lib/states.js";
import { state } from "./store.js";

function normaliser(s) {
  return String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

function contient(texte) {
  return !state.recherche || normaliser(texte).includes(normaliser(state.recherche));
}

/** La tâche correspond-elle à la recherche (titre + brief) ? */
export function correspond(t) {
  return contient(`${t.titre}\n${t.corps}`);
}

/** Un point « hors tâche » de /api/inbox correspond-il à la recherche ? */
export function correspondPoint(item) {
  const q = item.question || {};
  return contient(`${item.titre || ""}\n${q.texte || q.question || ""}`);
}

/** a_moi | en_cours | a_lancer | archivees */
export function segmentDe(t) {
  return t.segment || (TASK_STATUSES[t.statut_ui] || {}).segment || "a_lancer";
}

export const estArchivee = (t) => segmentDe(t) === "archivees";

function rang(t) {
  return (TASK_STATUSES[t.statut_ui] || {}).rank ?? 9;
}

/** Urgence d'abord (répondre, échec, relire, trancher, en cours, brouillon), puis le plus récent. */
export function trier(taches) {
  return taches.slice().sort((a, b) => (rang(a) - rang(b))
    || String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
}

/** Rend `enfants` (dans l'ordre) comme enfants de `parent` sans déplacer ceux déjà en place
 *  (déplacer un nœud qui contient le focus le lui ferait perdre). */
export function reconcilier(parent, enfants) {
  const voulus = new Set(enfants);
  for (const el of [...parent.children]) if (!voulus.has(el)) el.remove();
  let curseur = parent.firstElementChild;
  for (const el of enfants) {
    if (el === curseur) { curseur = curseur.nextElementSibling; continue; }
    parent.insertBefore(el, curseur);
  }
}
