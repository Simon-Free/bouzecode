// [desc] Changer une tâche de chantier : le geste commun au glisser-déposer et à « Déplacer vers… » (clic ou Entrée sur la poignée, menu ⋯) — tâche occupée pendant l'appel, toast avec « Annuler », tâche surlignée à l'arrivée. [/desc]

import { h, busy, toast, highlight } from "../lib/ui.js";
import { state, chantierParId } from "./store.js";
import * as act from "./actions.js";

const nomDe = (id) => (id ? ((chantierParId(id) || {}).titre || "ce chantier") : "Sans chantier");

function destinations(t) {
  const actifs = ((state.lignes && state.lignes.chantiers) || []).filter((c) => c.etat === "active" || c.etat === "en_pause");
  return [...actifs.map((c) => ({ id: c.macro_id, titre: c.titre })), { id: "", titre: "Sans chantier" }]
    .map((d) => ({ ...d, actuel: (t.macro_id || "") === d.id }));
}

/** La tâche est-elle dans le DOM ? On la montre (surlignage + défilement) ; sinon on le dit. */
function montrerArrivee(rec) {
  requestAnimationFrame(() => {
    if (rec.el.isConnected && rec.el.offsetParent !== null) highlight(rec.el);
  });
}

/** PATCH du chantier, la tâche marquée « Déplacement… » pendant l'appel (R1/R2). Lève en cas d'échec. */
async function changerChantier(rec, destId) {
  rec.el.classList.add("is-saving");
  rec.el.setAttribute("aria-busy", "true");
  try {
    await act.modifierTache(rec.id, { macro_id: destId });
    await act.rafraichir();
  } finally {
    rec.el.classList.remove("is-saving");
    rec.el.removeAttribute("aria-busy");
  }
}

/** Déplace la tâche `rec` dans le chantier `destId` ("" = Sans chantier) : signal pendant l'appel,
 *  toast « Tâche déplacée dans « X » — Annuler », tâche surlignée ; erreur → toast + Réessayer. */
export async function deplacerTache(rec, destId) {
  const origine = rec.t.macro_id || "";
  if (origine === destId) { toast.info(`La tâche est déjà dans « ${nomDe(destId)} ».`); return; }
  try {
    await changerChantier(rec, destId);
  } catch (e) {
    toast.err(`Déplacement impossible : ${e.message}`, { action: { label: "Réessayer", fn: () => deplacerTache(rec, destId) } });
    return;
  }
  toast.ok(`Tâche déplacée dans « ${nomDe(destId)} ».`, { timeout: 10000, action: { label: "Annuler", fn: async () => {
    await changerChantier(rec, origine);
    toast.ok(`Tâche remise dans « ${nomDe(origine)} ».`);
    montrerArrivee(rec);
  } } });
  montrerArrivee(rec);
}

/** Ouvre le dialogue « Déplacer vers… » pour la tâche `rec`. */
export function deplacerVers(rec) {
  const dlg = h("dialog", { class: "ui-dialog", "aria-labelledby": "bz-deplacer-t" });
  const retour = document.activeElement;
  const fermer = () => {
    dlg.close();
    dlg.remove();
    const cible = retour && retour.isConnected ? retour : rec.titre;
    if (cible && cible.isConnected) cible.focus();
  };
  const liste = h("div", { class: "bz-depots", role: "group", "aria-label": "Chantiers" });
  for (const d of destinations(rec.t)) {
    const b = h("button", { type: "button", class: "btn btn--ghost bz-deplacer__choix", disabled: d.actuel }, d.titre,
      d.actuel ? h("span", { class: "bz-muted" }, " — actuel") : null);
    b.addEventListener("click", () => busy(b, "Déplacement…", async () => {
      await deplacerTache(rec, d.id);
      fermer();
    }));
    liste.appendChild(b);
  }
  // Flèches haut / bas : passer d'un chantier à l'autre sans Tab.
  liste.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const actifs = [...liste.querySelectorAll("button:not([disabled])")];
    const i = actifs.indexOf(document.activeElement);
    e.preventDefault();
    actifs[(i + (e.key === "ArrowDown" ? 1 : actifs.length - 1)) % actifs.length]?.focus();
  });
  const annuler = h("button", { type: "button", class: "btn" }, "Annuler");
  annuler.addEventListener("click", fermer);
  dlg.append(h("div", { class: "ui-dialog__body" },
    h("h2", { class: "ui-dialog__title", id: "bz-deplacer-t" }, "Déplacer vers…"),
    h("p", { class: "ui-dialog__text" }, rec.t.titre || ""), liste),
  h("div", { class: "ui-dialog__actions" }, annuler));
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); fermer(); });
  document.body.appendChild(dlg);
  dlg.showModal();
  (liste.querySelector("button:not([disabled])") || annuler).focus();
}
