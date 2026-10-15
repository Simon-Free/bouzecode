// État partagé de la vue d'enquête et petites aides d'affichage (aucune dépendance au DOM de page).
import { api } from "../lib/ui.js";

export const etat = {
  agent: "",
  frise: null,          // réponse de /frise
  tour: null,           // numéro du tour affiché
  element: null,        // indice de l'élément à mettre en évidence
  vue: "tours",
  details: new Map(),   // cache des tours déjà chargés
};

export function url(chemin) {
  return `/api/enquete/${encodeURIComponent(etat.agent)}${chemin}`;
}

export async function chargerTour(n) {
  if (!etat.details.has(n)) etat.details.set(n, await api("GET", url(`/tours/${n}`)));
  return etat.details.get(n);
}

const FMT = new Intl.NumberFormat("fr-FR");
export function nombre(n) { return FMT.format(Math.round(Number(n) || 0)); }

export function kilo(n) {
  const v = Number(n) || 0;
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)} k` : String(Math.round(v));
}

export const LIBELLES_CACHE = { cached: "cache lu", "new-cache": "écrit au cache", fresh: "plein tarif" };

/** Le hash décodé, sans jamais lever : un « % » collé ou tapé tel quel (« #recherche-50% ») est
 *  une séquence mal formée pour `decodeURIComponent`, qui faisait planter la page. */
export function ancre() {
  const brut = location.hash.slice(1);
  try { return decodeURIComponent(brut); } catch (_) { return brut; }
}

// Tour désigné par l'URL. `naviguer` écrit le hash tout de suite, mais `etat.tour` n'est mis
// à jour qu'au `hashchange`, dans une tâche ULTÉRIEURE : une touche pressée entre les deux
// (j puis k très vite, ou répétition d'une touche maintenue) partirait d'un tour périmé.
export function tourDemande() {
  const m = /^tour-(\d+)(?:\/|$)/.exec(ancre());
  return m ? Number(m[1]) : etat.tour;
}

export function naviguer(hash) {
  if (location.hash !== hash) location.hash = hash;
}
