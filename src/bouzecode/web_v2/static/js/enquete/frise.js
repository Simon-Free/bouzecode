// Frise des tours : une ligne par appel LLM (barre empilée cache lu / écrit / plein tarif + sortie),
// marqueurs, filtre « anormaux », sélection et navigation j/k.
import { h, empty } from "../lib/ui.js";
import { etat, kilo, nombre, naviguer, tourDemande } from "./etat.js";

let seulementAnormaux = false;

function tours() {
  const tous = (etat.frise && etat.frise.tours) || [];
  return seulementAnormaux ? tous.filter((t) => t.anormal) : tous;
}

function total(t) { return t.plein_tarif + t.cache_lu + t.cache_ecrit; }

function barre(t, max) {
  const part = (v) => `${(100 * v) / max}%`;
  return h("span", { class: "eq-barre", "aria-hidden": "true" },
    h("span", { class: "eq-barre__lu", style: { width: part(t.cache_lu) } }),
    h("span", { class: "eq-barre__ecrit", style: { width: part(t.cache_ecrit) } }),
    h("span", { class: "eq-barre__plein", style: { width: part(t.plein_tarif) } }),
    h("span", { class: "eq-barre__sortie", style: { width: part(t.sortie) } }));
}

function marqueurs(t) {
  const libelles = etat.frise.libelles_marqueurs || {};
  return h("span", { class: "eq-marques" }, t.marqueurs.map((m) =>
    h("span", { class: "eq-marque", "data-marque": m, title: libelles[m] || m }, libelles[m] || m)));
}

function titre(t) {
  const lu = total(t) ? Math.round((100 * t.cache_lu) / total(t)) : 0;
  return `Tour ${t.tour} — entrée ${nombre(total(t))} tokens (cache lu ${lu} %), sortie ${nombre(t.sortie)}`
    + (t.duree_s != null ? `, ${t.duree_s} s` : "") + (t.outils.length ? ` — ${t.outils.join(", ")}` : "")
    + (t.cause_cache ? `\nCache raté : ${t.cause_cache}` : "");
}

function ligne(t, max) {
  const actif = t.tour === etat.tour;
  const bouton = h("button", {
    type: "button", class: "eq-ligne", "data-tour": t.tour, title: titre(t),
    "aria-current": actif ? "true" : null, "data-anormal": t.anormal ? "1" : null,
    onclick: () => naviguer(`#tour-${t.tour}`),
  },
  h("span", { class: "eq-ligne__num" }, `#${t.tour}`),
  h("span", { class: "eq-ligne__tokens" }, kilo(total(t))),
  barre(t, max),
  marqueurs(t));
  return h("li", {}, bouton);
}

export function rendreFrise() {
  const liste = document.getElementById("eq-liste");
  const visibles = tours();
  liste.removeAttribute("aria-busy");
  if (!visibles.length) {
    empty(liste, { title: seulementAnormaux ? "Aucun tour anormal." : "Aucun tour.", inline: true });
    return;
  }
  const max = Math.max(1, ...visibles.map((t) => total(t) + t.sortie));
  liste.replaceChildren(...visibles.map((t) => ligne(t, max)));
  const actif = liste.querySelector('[aria-current="true"]');
  if (actif) actif.scrollIntoView({ block: "nearest" });
}

export function voisin(sens) {
  const visibles = tours();
  const courant = tourDemande();
  const i = visibles.findIndex((t) => t.tour === courant);
  const cible = visibles[Math.min(Math.max(i + sens, 0), visibles.length - 1)];
  if (cible) naviguer(`#tour-${cible.tour}`);
}

export function brancherFiltre() {
  const case_ = document.getElementById("eq-anormaux");
  case_.addEventListener("change", () => { seulementAnormaux = case_.checked; rendreFrise(); });
}
