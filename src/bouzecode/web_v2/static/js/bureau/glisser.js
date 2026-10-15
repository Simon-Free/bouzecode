// [desc] Glisser-déposer du Bureau aux événements pointeur (souris, stylet, doigt) : une tâche vers un chantier, un chantier à une autre place. Cibles compactes (chantiers repliés le temps du geste, ou plateau de chantiers en mode Statut), défilement automatique près des bords, chantier survolé qui s'entrouvre, indicateur d'insertion, Échap pour annuler. [/desc]
//
// Pourquoi pas l'API HTML5 `draggable` : pas de défilement automatique fiable, pas de tactile,
// pas d'Échap maîtrisable, et une tâche devait être lâchée sur un en-tête de chantier souvent
// hors écran (il fallait replier tous les chantiers à la main). Ici :
//   - mode Chantier : dès que le geste démarre, TOUS les chantiers se replient (seuls les
//     en-têtes restent, chacun une cible) et la page se recale pour garder le chantier d'origine
//     sous le pointeur ; un chantier survolé ~0,7 s s'entrouvre pour montrer son contenu ;
//   - mode Statut : un plateau fixe liste les chantiers comme cibles compactes ;
//   - près du haut / du bas de la fenêtre, la page défile seule (plus vite près du bord) ;
//   - Échap (ou l'interruption du pointeur) annule sans rien envoyer.
// Clic sans glisser, ou Entrée sur la poignée (bouton) : l'alternative sans glisser (`surClic`).

import { h, toast } from "../lib/ui.js";
import { state, chantierParId } from "./store.js";

const SEUIL = 6; // px parcourus avant qu'un appui devienne un glisser
const BORD = 90; // px : zone de défilement automatique en haut et en bas
const VITESSE_MAX = 26; // px par image au ras du bord
const OUVERTURE_MS = 700; // survol d'un chantier replié avant qu'il s'entrouvre

let g = null; // le glisser en cours
let clicIgnore = null; // poignée dont le clic qui suit un glisser ne doit rien ouvrir

export const glisserEnCours = () => g !== null;

function annoncer(texte) {
  let zone = document.getElementById("bz-dnd-live");
  if (!zone) {
    zone = h("div", { id: "bz-dnd-live", class: "sr-only", role: "status", "aria-live": "assertive" });
    document.body.appendChild(zone);
  }
  zone.textContent = texte;
}

const nomChantier = (id) => (id ? ((chantierParId(id) || {}).titre || "ce chantier") : "Sans chantier");

// ---------------------------------------------------------------- cibles

/** Plateau du mode Statut : les chantiers actifs + « Sans chantier », en cibles compactes. */
function plateau(origine) {
  const actifs = ((state.lignes && state.lignes.chantiers) || []).filter((c) => c.etat === "active" || c.etat === "en_pause");
  const cibles = [...actifs.map((c) => ({ id: c.macro_id, titre: c.titre })), { id: "", titre: "Sans chantier" }];
  return h("div", { class: "bz-plateau", "aria-hidden": "true" },
    h("p", { class: "bz-plateau__titre" }, "Déposer dans…"),
    h("div", { class: "bz-plateau__liste" }, cibles.map((d) => h("div", { class: "bz-plateau__cible", "data-drop": d.id,
      "data-actuel": d.id === origine ? "true" : null }, d.titre, d.id === origine ? h("span", { class: "bz-muted" }, " · actuel") : null))));
}

function trouverCible(x, y) {
  const sous = document.elementFromPoint(x, y);
  if (g.o.type === "tache") {
    const zone = sous && sous.closest("[data-drop]");
    return zone ? { el: zone, id: zone.dataset.drop } : null;
  }
  const zone = sous && sous.closest(".bz-ch[data-drop]:not([data-drop=''])");
  if (!zone || zone === g.source) return null;
  const r = zone.getBoundingClientRect();
  return { el: zone, id: zone.dataset.drop, apres: y > r.top + r.height / 2 };
}

function texteCible(c) {
  if (!c) return g.o.type === "tache" ? "Survole un chantier…" : "Survole la place voulue…";
  if (g.o.type === "chantier") return `${c.apres ? "Après" : "Avant"} « ${nomChantier(c.id)} »`;
  return c.id === g.origine ? `Déjà dans « ${nomChantier(c.id)} »` : `Déposer dans « ${nomChantier(c.id)} »`;
}

/** Entrouvre un chantier replié survolé (le temps du survol seulement). */
function entrouvrir(el) {
  const corps = el.querySelector(":scope > .bz-ch__corps");
  el.classList.add("is-peek");
  if (corps && corps.hidden) { corps.hidden = false; g.refermer = corps; }
}

function lacher(c) {
  c.el.classList.remove("is-drop-target", "is-insert-before", "is-insert-after", "is-peek");
  if (g.refermer) { g.refermer.hidden = true; g.refermer = null; }
}

function viser(c) {
  const meme = c && g.cible && c.el === g.cible.el && c.apres === g.cible.apres;
  if (meme || (!c && !g.cible)) return;
  clearTimeout(g.minuteur);
  if (g.cible) lacher(g.cible);
  g.cible = c;
  g.vers.textContent = texteCible(c);
  g.fantome.dataset.cible = c ? "true" : "false";
  if (!c) return;
  if (g.o.type === "chantier") { c.el.classList.add(c.apres ? "is-insert-after" : "is-insert-before"); return; }
  c.el.classList.add("is-drop-target");
  if (c.el.classList.contains("bz-ch")) g.minuteur = setTimeout(() => entrouvrir(c.el), OUVERTURE_MS);
}

// ---------------------------------------------------------------- défilement automatique

function vitesse(y, haut, bas) {
  if (y < haut + BORD) return -Math.ceil(VITESSE_MAX * Math.min(1, (haut + BORD - y) / BORD));
  if (y > bas - BORD) return Math.ceil(VITESSE_MAX * Math.min(1, (y - (bas - BORD)) / BORD));
  return 0;
}

function defiler() {
  if (!g) return;
  if (!g.plateau) {
    const bandeaux = document.getElementById("banners");
    const haut = bandeaux ? Math.max(0, bandeaux.getBoundingClientRect().bottom) : 0;
    const dy = vitesse(g.y, haut, window.innerHeight);
    if (dy) { window.scrollBy(0, dy); viser(trouverCible(g.x, g.y)); }
  } else {
    const liste = g.plateau.querySelector(".bz-plateau__liste");
    const r = liste.getBoundingClientRect();
    if (g.x >= r.left && g.x <= r.right) {
      const dy = vitesse(g.y, r.top - BORD + 24, r.bottom + BORD - 24);
      if (dy) { liste.scrollTop += dy; viser(trouverCible(g.x, g.y)); }
    }
  }
  g.raf = requestAnimationFrame(defiler);
}

// ---------------------------------------------------------------- début / fin

/** Mode Chantier : seuls les en-têtes restent ; `ancre` est recalé sous le pointeur. */
function compacter(ancre, y) {
  document.body.classList.add("bz-compact");
  if (!ancre) return;
  const r = ancre.getBoundingClientRect();
  window.scrollBy(0, r.top + r.height / 2 - y);
}

function demarrer(o, ev) {
  const source = typeof o.source === "function" ? o.source() : o.source;
  const vers = h("span", { class: "bz-ghost__vers" });
  const fantome = h("div", { class: "bz-ghost", "aria-hidden": "true" }, h("span", { class: "bz-ghost__quoi" }, `⠿ ${o.libelle()}`), vers);
  document.body.appendChild(fantome);
  g = { o, source, fantome, vers, cible: null, x: ev.clientX, y: ev.clientY, raf: 0, minuteur: 0, plateau: null,
    refermer: null, origine: o.origine ? o.origine() : "" };
  g.clavier = (e) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation();
    annuler();
  };
  document.addEventListener("keydown", g.clavier, true);
  source.classList.add("is-dragging");
  document.body.classList.add("bz-dragging");
  document.body.dataset.drag = o.type;
  if (state.mode === "chantier") compacter(o.type === "chantier" ? source : source.closest(".bz-ch"), ev.clientY);
  else if (o.type === "tache") {
    g.plateau = plateau(g.origine);
    const bandeaux = document.getElementById("banners");
    if (bandeaux) g.plateau.style.top = `${Math.max(48, bandeaux.getBoundingClientRect().bottom) + 16}px`;
    document.body.appendChild(g.plateau);
  }
  vers.textContent = texteCible(null);
  annoncer(`Déplacement de « ${o.libelle()} » : survole ${o.type === "tache" ? "un chantier" : "la place voulue"}, puis relâche. Échap annule.`);
  g.raf = requestAnimationFrame(defiler);
}

function suivre(x, y) {
  g.x = x;
  g.y = y;
  // Le fantôme reste dans la fenêtre : à gauche du pointeur près du bord droit.
  const l = g.fantome.offsetWidth || 0;
  const gx = x + 14 + l > window.innerWidth ? Math.max(0, x - 14 - l) : x + 14;
  g.fantome.style.transform = `translate(${gx}px, ${y + 10}px)`;
  viser(trouverCible(x, y));
}

/** Remet la page comme avant le geste ; `ancre` reste à la même hauteur à l'écran. */
function finir(ancre) {
  cancelAnimationFrame(g.raf);
  clearTimeout(g.minuteur);
  if (g.cible) lacher(g.cible);
  g.fantome.remove();
  if (g.plateau) g.plateau.remove();
  g.source.classList.remove("is-dragging");
  document.removeEventListener("keydown", g.clavier, true);
  const avant = ancre && ancre.isConnected && document.body.classList.contains("bz-compact")
    ? ancre.getBoundingClientRect().top : null;
  document.body.classList.remove("bz-dragging", "bz-compact");
  delete document.body.dataset.drag;
  if (avant !== null) window.scrollBy(0, ancre.getBoundingClientRect().top - avant);
  g = null;
  // Le rendu était différé pendant le geste (liste.js) : on rattrape.
  window.dispatchEvent(new CustomEvent("bz:render"));
}

function annuler() {
  if (!g) return;
  finir(g.o.type === "chantier" ? g.source : g.source.closest(".bz-ch") || g.source);
  toast.info("Déplacement annulé.");
  annoncer("Déplacement annulé.");
}

async function deposer() {
  const { o, cible, source } = g;
  finir(cible ? cible.el : source);
  if (!cible) {
    toast.info(o.type === "tache" ? "Rien n'a bougé : relâche la tâche sur un chantier." : "Rien n'a bougé : relâche le chantier entre deux autres.");
    return;
  }
  await o.deposer(cible);
}

// ---------------------------------------------------------------- poignée

/**
 * Rend `poignee` (un bouton) glissable.
 * @param {HTMLElement} poignee
 * @param {{type:"tache"|"chantier", source:HTMLElement|(()=>HTMLElement), libelle:()=>string,
 *          origine?:()=>string, surClic:()=>any, deposer:(cible:{id:string, apres?:boolean})=>Promise<any>}} o
 */
export function rendreGlissable(poignee, o) {
  poignee.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || g) return;
    e.preventDefault(); // ni sélection de texte ni défilement tactile depuis la poignée
    const depart = { x: e.clientX, y: e.clientY, id: e.pointerId };
    // Capture : les mouvements arrivent à la poignée même hors d'elle (souris rapide, doigt).
    try { poignee.setPointerCapture(e.pointerId); } catch (_) { depart.sansCapture = true; }
    const bouger = (ev) => {
      if (ev.pointerId !== depart.id || (depart.glisse && !g)) return; // annulé : on ne repart pas
      if (!g && Math.hypot(ev.clientX - depart.x, ev.clientY - depart.y) < SEUIL) return;
      if (!g) { demarrer(o, ev); depart.glisse = true; }
      if (g) suivre(ev.clientX, ev.clientY);
    };
    const fin = (ev) => {
      if (ev.pointerId !== depart.id) return;
      poignee.removeEventListener("pointermove", bouger);
      poignee.removeEventListener("pointerup", fin);
      poignee.removeEventListener("pointercancel", fin);
      if (!depart.glisse) return; // simple clic : « click » ouvrira l'alternative
      // Un glisser (même annulé par Échap) n'est pas un clic : le « click » qui suit ne doit rien ouvrir.
      clicIgnore = poignee;
      setTimeout(() => { if (clicIgnore === poignee) clicIgnore = null; }, 0);
      if (!g || g.o !== o) return;
      if (ev.type === "pointercancel") annuler(); else deposer();
    };
    poignee.addEventListener("pointermove", bouger);
    poignee.addEventListener("pointerup", fin);
    poignee.addEventListener("pointercancel", fin);
  });
  poignee.addEventListener("click", (e) => {
    e.stopPropagation();
    if (clicIgnore === poignee) { clicIgnore = null; return; }
    o.surClic();
  });
}
