// [desc] Bureau, mode « Chantier » (SPEC §4.3) : un bloc par chantier, tâches triées par urgence (celles qui t'attendent en tête, surlignées), archivées repliées en bas ; « Hors chantier » en tête s'il y a des points d'agents sans tâche ; « Sans chantier » puis les chantiers archivés en bas. [/desc]

import { h } from "../lib/ui.js";
import { state, basculerArchives } from "./store.js";
import { correspond, estArchivee, trier, reconcilier } from "./filtre.js";
import { renderTache, enEdition } from "./tache.js";
import { pointsParTache, pointsHorsTache, lignesHorsTache } from "./attente.js";
import { section, majEntete } from "./sections.js";
import { ARCHIVES } from "./chantier.js";

// ---------------------------------------------------------------- blocs fixes

let hors = null;
let archivesCh = null;

function blocHors() {
  if (hors) return hors;
  const compte = h("span", { class: "count", "data-tone": "warn" });
  const corps = h("div", { class: "bz-sec__corps" });
  hors = { compte, corps, el: h("section", { class: "bz-sec bz-sec--hors", "data-sec": "hors" },
    h("h2", { class: "bz-sec__titre", title: "Questions et échecs d'agents lancés hors tâche (page Agents)" },
      "Hors chantier ", compte), corps) };
  return hors;
}

function blocChantiersArchives() {
  if (archivesCh) return archivesCh;
  const bascule = h("button", { type: "button", class: "bz-sec__bascule", "aria-expanded": "false" });
  bascule.addEventListener("click", () => basculerArchives("chantiers"));
  const corps = h("div", { class: "bz-sec__corps" });
  archivesCh = { bascule, corps, el: h("section", { class: "bz-sec", "data-sec": "chantiers-archives" },
    h("h2", { class: "bz-sec__titre" }, bascule), corps) };
  return archivesCh;
}

// ---------------------------------------------------------------- un chantier

const visible = (t) => correspond(t) || enEdition(t.id);

function majArchives(s, cle, archivees, points) {
  const ouvert = state.archivesOuvertes.has(cle);
  const n = archivees.length;
  s.archives.el.hidden = n === 0;
  s.archives.btn.textContent = `${ouvert ? "▾" : "▸"} ${n} archivée${n > 1 ? "s" : ""}`;
  s.archives.btn.setAttribute("aria-expanded", ouvert ? "true" : "false");
  s.archives.corps.hidden = !ouvert;
  reconcilier(s.archives.corps, ouvert ? trier(archivees).map((t) => renderTache(t, { point: points.get(t.id) })) : []);
}

function majCorps(s, actives) {
  const els = actives.map((x) => x.el);
  const vide = s.corps.querySelector(".bz-ch__vide") || h("p", { class: "bz-muted bz-ch__vide" }, "Aucune tâche pour l'instant.");
  reconcilier(s.corps, els.length ? els : [vide]);
}

/** Rend un chantier (ou « Sans chantier » si `c` est null) ; null si rien à montrer (recherche). */
function rendreChantier(id, c, taches, points) {
  const vues = taches.filter(visible);
  if (state.recherche && !vues.length) return null;
  const s = section(id);
  majEntete(s, id, c);
  const replie = !!(id && state.replies.has(id));
  const archive = !!(c && ARCHIVES.includes(c.etat));
  s.el.classList.toggle("is-collapsed", replie);
  // Cible du glisser-déposer (glisser.js) : tout chantier non archivé, et « Sans chantier ».
  if (archive) delete s.el.dataset.drop; else s.el.dataset.drop = id;
  s.corps.hidden = replie;
  s.ajout.hidden = replie || archive;
  const actives = trier(vues.filter((t) => !estArchivee(t))).map((t) => ({ el: renderTache(t, { point: points.get(t.id) }) }));
  if (s.aide) s.aide.hidden = !actives.length || replie;  // « Sans chantier » : l'aide n'a de sens qu'avec des orphelines
  majCorps(s, actives);
  majArchives(s, id || "__sans", replie ? [] : vues.filter(estArchivee), points);
  return s.el;
}

// ---------------------------------------------------------------- page

function blocsHors() {
  const pts = pointsHorsTache();
  if (!pts.length) return [];
  const b = blocHors();
  b.compte.textContent = String(pts.length);
  reconcilier(b.corps, lignesHorsTache(pts));
  return [b.el];
}

function blocsArchives(archives, points) {
  const els = archives.map((c) => rendreChantier(c.macro_id, c, c.lignes || [], points)).filter(Boolean);
  if (!els.length) return [];
  const b = blocChantiersArchives();
  const ouvert = state.archivesOuvertes.has("chantiers") || !!state.recherche;
  b.bascule.textContent = `${ouvert ? "▾" : "▸"} Chantiers archivés (${els.length})`;
  b.bascule.setAttribute("aria-expanded", ouvert ? "true" : "false");
  b.corps.hidden = !ouvert;
  reconcilier(b.corps, ouvert ? els : []);
  return [b.el];
}

/** Les blocs du mode Chantier, dans l'ordre, prêts à être posés dans la liste. */
export function blocsChantier() {
  const d = state.lignes;
  const points = pointsParTache();
  const chantiers = d.chantiers || [];
  const actifs = chantiers.filter((c) => !ARCHIVES.includes(c.etat));
  const archives = chantiers.filter((c) => ARCHIVES.includes(c.etat));
  const blocsActifs = actifs.map((c) => rendreChantier(c.macro_id, c, c.lignes || [], points));
  const sans = rendreChantier("", null, d.non_rattachees || [], points);
  return [...blocsHors(), ...blocsActifs, sans, ...blocsArchives(archives, points)].filter(Boolean);
}
