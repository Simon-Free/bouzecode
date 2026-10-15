// Point d'entrée de la vue d'enquête : chargement de la frise, onglets, permaliens (#tour-103/element-12,
// #note, #saturation-103, #recherche) et raccourcis clavier (j/k, ←/→, /).
import { api, failed, skeleton, empty } from "../lib/ui.js";
import { etat, url, nombre, naviguer, ancre } from "./etat.js";
import { rendreFrise, voisin, brancherFiltre } from "./frise.js";
import { afficherTour } from "./tour.js";
import { afficherNote } from "./note.js";
import { afficherSaturation } from "./saturation.js";
import { rechercher } from "./recherche.js";

const racine = document.querySelector(".eq");
etat.agent = racine ? racine.dataset.agent : "";

function montrerVue(vue) {
  etat.vue = vue;
  document.querySelectorAll(".eq-vue").forEach((s) => { s.hidden = s.dataset.vue !== vue; });
  document.querySelectorAll(".eq-onglets .tab").forEach((t) => {
    t.setAttribute("aria-selected", String(t.dataset.vue === vue));
    if (t.dataset.vue === vue) t.hidden = false;
  });
}

function lireHash() {
  const h = ancre();
  const tour = /^tour-(\d+)(?:\/element-(\d+))?$/.exec(h);
  if (tour) return { vue: "tours", tour: Number(tour[1]), element: tour[2] != null ? Number(tour[2]) : null };
  const satur = /^saturation(?:-(\d+))?$/.exec(h);
  if (satur) return { vue: "saturation", tour: satur[1] ? Number(satur[1]) : null };
  if (h.startsWith("recherche-")) return { vue: "recherche", q: h.slice("recherche-".length) };
  if (h === "note") return { vue: "note" };
  return { vue: "tours", tour: null, element: null };
}

function premierTourUtile() {
  const t = etat.frise.tours;
  const anormal = t.find((x) => x.anormal);
  return (anormal || t[t.length - 1] || {}).tour;
}

function suivreHash() {
  if (!etat.frise) return;
  const cible = lireHash();
  montrerVue(cible.vue);
  if (cible.vue === "note") afficherNote();
  else if (cible.vue === "saturation") afficherSaturation(cible.tour);
  else if (cible.vue === "recherche") rechercher(cible.q);
  else {
    etat.tour = cible.tour ?? premierTourUtile() ?? null;
    rendreFrise();
    //  Session sans aucun tour : rien à charger (on appelait /tours/undefined, en 404).
    if (etat.tour == null) {
      empty(document.getElementById("eq-tour"), { title: "Aucun tour dans cette session.",
        text: "L'agent n'a encore fait aucun appel au modèle." });
      return;
    }
    afficherTour(etat.tour, cible.element);
  }
}

function resumer(f) {
  const n = f.tours.length;
  document.getElementById("eq-resume").textContent =
    `${f.modele || "modèle inconnu"} · ${n} tours · coût ${Number(f.total_cout).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} (unités du tarif) · `
    + `${f.nb_anormaux} tour(s) anormal(aux)`;
}

const SENS = { j: 1, ArrowRight: 1, k: -1, ArrowLeft: -1 };

function clavier(ev) {
  const saisie = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
  if (ev.key === "/" && !saisie) { ev.preventDefault(); document.getElementById("eq-q").focus(); return; }
  const modifie = ev.ctrlKey || ev.metaKey || ev.altKey;
  if (saisie || modifie || etat.vue !== "tours" || !(ev.key in SENS)) return;
  ev.preventDefault();
  voisin(SENS[ev.key]);
}

function brancher() {
  document.querySelectorAll(".eq-onglets .tab").forEach((t) => t.addEventListener("click", () => {
    const v = t.dataset.vue;
    const tour = etat.tour ?? premierTourUtile();
    naviguer(v === "tours" ? (tour == null ? "#" : `#tour-${tour}`) : v === "recherche"
      ? `#recherche-${encodeURIComponent(document.getElementById("eq-q").value.trim())}` : `#${v}`);
  }));
  document.getElementById("eq-recherche").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = document.getElementById("eq-q").value.trim();
    if (q.length >= 2) naviguer(`#recherche-${encodeURIComponent(q)}`);
  });
  brancherFiltre();
  window.addEventListener("hashchange", suivreHash);
  document.addEventListener("keydown", clavier);
}

async function demarrer() {
  const liste = document.getElementById("eq-liste");
  skeleton(liste, 12);
  try {
    etat.frise = await api("GET", url("/frise"));
    resumer(etat.frise);
    suivreHash();
  } catch (err) {
    document.getElementById("eq-resume").textContent = "Enquête indisponible.";
    failed(document.getElementById("eq-tour"), err, demarrer, { title: "Impossible de charger la session." });
    liste.replaceChildren();
  }
}

if (racine) { brancher(); demarrer(); }
