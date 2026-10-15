// [desc] Ce qui attend un geste, dans les deux modes du Bureau : points de /api/inbox rattachés à une tâche (portés PAR la tâche) ou hors tâche (lignes « point » avec leur bande d'action toujours visible). Rendu keyé, jamais reconstruit pendant qu'on y agit (R8). [/desc]
//
// /api/inbox ne produit qu'UN point par tâche : il est affiché SUR la tâche (une seule
// apparition, quel que soit le mode). Seuls les points sans tâche (conversations libres,
// lancements hors tâche) deviennent des lignes à part. Par défaut une ligne ne montre que
// le motif (ce qu'il faut faire), le titre, une ligne de résumé, puis la bande d'action : la
// question avec ses options, ou les gestes (Continuer, Relancer, Ouvrir la conversation).

import { h, relTime } from "../lib/ui.js";
import { state } from "./store.js";
import { contenuCarte, signature, occupee } from "./inbox_carte.js";
import { correspondPoint } from "./filtre.js";
import { MOTIFS, badgeMotif } from "./attention.js";

const items = () => (state.inbox && state.inbox.items) || [];

/** micro_id -> point d'attente de la tâche. */
export function pointsParTache() {
  const m = new Map();
  for (const it of items()) {
    const id = it.tache && it.tache.micro_id;
    if (id && !m.has(id)) m.set(id, it);
  }
  return m;
}

/** Points sans tâche (conversations libres, lancements hors tâche), filtrés par la recherche. */
export function pointsHorsTache() {
  return items().filter((it) => !(it.tache && it.tache.micro_id) && correspondPoint(it));
}

/** La ligne secondaire d'un point : la question, sinon la raison, sinon le résumé du récap. */
export function resumePoint(it) {
  if (it.type === "plan") return "Plan à valider";
  if (it.type === "question") return texteQuestion(it.question || {});
  return it.raison || resumeRecap(it.recap || {});
}

const texteQuestion = (q) => q.texte || q.question || "";
const resumeRecap = (r) => r.resume || (r.fait || [])[0] || "";

// ---------------------------------------------------------------- lignes hors tâche

const lignes = new Map(); // id -> {el, corps, ouvert, sig, sigCorps}

function infobulle(it) {
  return [(MOTIFS[it.motif] || {}).aide, it.projet_slug, it.sous_agent ? "sous-agent" : "", relTime(it.depuis)]
    .filter(Boolean).join(" · ");
}

function majCorpsPoint(rec) {
  const sig = signature(rec.it);
  if (sig === rec.sigCorps || occupee(rec.corps)) return;
  rec.sigCorps = sig;
  rec.corps.replaceChildren(...contenuCarte(rec.it));
}

function construirePoint() {
  const titre = h("span", { class: "bz-task__titre" });
  const sous = h("span", { class: "bz-task__meta" });
  const slotBadge = h("span", { class: "bz-task__badge" });
  const ligne = h("div", { class: "bz-task__row" }, slotBadge, h("span", { class: "bz-task__txt" }, titre, sous));
  const corps = h("div", { class: "bz-task__attente" });
  const el = h("article", { class: "bz-task bz-point is-attention" }, ligne, corps);
  return { el, ligne, titre, sous, slotBadge, corps, it: null, sig: "", sigCorps: "" };
}

/** La question est dans la bande : la ligne ne la répète pas. */
const resumeLigne = (it) => (it.type === "question" || it.type === "plan" ? "" : resumePoint(it));

function majPoint(rec, it) {
  rec.it = it;
  const motif = MOTIFS[it.motif] ? it.motif : "question";
  const sig = JSON.stringify([it.id, motif, it.titre, resumeLigne(it), infobulle(it)]);
  if (sig !== rec.sig) {
    rec.sig = sig;
    rec.el.dataset.id = it.id;
    rec.el.dataset.type = it.type;
    rec.el.dataset.motif = motif;
    rec.slotBadge.replaceChildren(badgeMotif(motif));
    rec.titre.textContent = it.titre || "Sans titre";
    rec.sous.textContent = resumeLigne(it);
    rec.sous.hidden = !rec.sous.textContent;
    rec.ligne.title = infobulle(it);
  }
  majCorpsPoint(rec);
}

/** Les lignes des points hors tâche, dans l'ordre (nœuds gardés d'un rendu à l'autre). */
export function lignesHorsTache(points) {
  const gardees = new Set();
  const els = points.map((it) => {
    gardees.add(it.id);
    const rec = lignes.get(it.id) || construirePoint();
    lignes.set(it.id, rec);
    majPoint(rec, it);
    return rec.el;
  });
  for (const [id, rec] of lignes) {
    if (!gardees.has(id) && !rec.el.querySelector("[aria-busy='true']")) lignes.delete(id);
  }
  return els;
}
