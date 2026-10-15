// Histoire de la note de travail : courbe de taille, compactions, chaque ajout tour par tour, recherche.
import { h, api, skeleton, failed, empty } from "../lib/ui.js";
import { url, nombre, kilo, naviguer } from "./etat.js";
import { courbe } from "./svg.js";

let dernier = null;

function graphe(donnees) {
  const points = donnees.courbe.map((p) => ({ x: p.tour, y: p.taille }));
  const marques = points.filter((p) => donnees.compactions.includes(p.x));
  return courbe(points, {
    titre: "Taille de la note (caractères) au fil des tours",
    format: (v) => kilo(v), marques, surClic: (tour) => naviguer(`#tour-${tour}`),
  });
}

function entree(e) {
  const tete = h("summary", { class: "eq-note__tete" },
    h("button", { type: "button", class: "btn btn--ghost btn--sm", onclick: (ev) => { ev.preventDefault(); naviguer(`#tour-${e.tour}`); } }, `Tour ${e.tour}`),
    h("span", { class: "eq-note__delta" }, e.compaction ? `compaction : −${nombre(e.retire)} car.`
      : `+${nombre(e.taille_ajout)} car.`),
    h("span", { class: "eq-note__taille" }, `note : ${nombre(e.taille)} car.`),
    e.appels.length ? h("span", { class: "eq-note__appels" }, `${e.appels.length} appel(s) Methodology`) : null);
  return h("details", { class: "eq-note", "data-compaction": e.compaction ? "1" : null }, tete,
    e.compaction ? h("div", {}, h("h4", {}, "Ce qui a disparu (début)"), h("pre", { class: "eq-pre eq-pre--avant" }, e.disparu)) : null,
    h("h4", {}, e.ajoute_tronque ? "Ajouté (aperçu)" : "Ajouté"), h("pre", { class: "eq-pre" }, e.ajoute || "—"),
    e.appels.length ? h("details", { class: "eq-appel" }, h("summary", {}, "Texte des appels Methodology"),
      e.appels.map((t) => h("pre", { class: "eq-pre" }, t))) : null);
}

function liste(donnees, zone) {
  if (!donnees.entrees.length) {
    empty(zone, { title: donnees.q ? `Aucun ajout ne contient « ${donnees.q} ».` : "Note vide.", inline: true });
    return;
  }
  zone.replaceChildren(...donnees.entrees.filter((e) => e.taille_ajout || e.compaction || donnees.q).map(entree));
}

async function filtrer(q, zone) {
  skeleton(zone, 4);
  try {
    const d = await api("GET", url(`/methodologie?q=${encodeURIComponent(q)}`));
    liste(d, zone);
  } catch (err) {
    failed(zone, err, () => filtrer(q, zone));
  }
}

function barre(zone) {
  let minuteur = null;
  const champ = h("input", { class: "input", type: "search", id: "eq-note-q", placeholder: "Chercher dans la note…",
    oninput: () => { clearTimeout(minuteur); minuteur = setTimeout(() => filtrer(champ.value.trim(), zone), 300); } });
  return h("div", { class: "eq-note__barre" }, h("label", { class: "sr-only", for: "eq-note-q" }, "Chercher dans la note"), champ);
}

export async function afficherNote() {
  const vue = document.getElementById("vue-note");
  if (dernier) return;
  skeleton(vue, 6);
  try {
    dernier = await api("GET", url("/methodologie"));
    const zone = h("div", { class: "eq-note__liste" });
    const fin = dernier.courbe[dernier.courbe.length - 1] || { taille: 0 };
    vue.replaceChildren(
      h("p", { class: "eq-intro" }, `La note est relue à chaque tour. Elle fait aujourd'hui ${nombre(fin.taille)} caractères ; `
        + (dernier.compactions.length ? `${dernier.compactions.length} compaction(s).` : "aucune compaction n'a eu lieu.")),
      graphe(dernier), barre(zone), zone);
    liste(dernier, zone);
  } catch (err) {
    dernier = null;
    failed(vue, err, afficherNote);
  }
}
