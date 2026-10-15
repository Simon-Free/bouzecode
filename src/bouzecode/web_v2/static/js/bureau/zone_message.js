// [desc] Zone de saisie courte ouverte sous un geste (consigne, message joint à « Continuer ») : texte gardé et erreur affichée sous le champ en cas d'échec (R4), Échap / « Annuler » referme. [/desc]

import { h, busy } from "../lib/ui.js";

/**
 * Ouvre la zone juste après `apres` (une seule à la fois dans `conteneur`).
 * @param {{aria:string, placeholder:string, bouton:string, occupe:string, obligatoire?:string,
 *          envoyer:(text:string)=>Promise<void>}} o  `envoyer` lève une Error au message lisible.
 */
export function ouvrirZoneMessage(conteneur, apres, o) {
  const champ = h("textarea", { class: "textarea", rows: "2", "aria-label": o.aria, placeholder: o.placeholder });
  const ok = h("button", { type: "button", class: "btn btn--primary btn--sm" }, o.bouton);
  const fermer = h("button", { type: "button", class: "btn btn--sm" }, "Annuler");
  const err = h("p", { class: "field__error", role: "alert" });
  const zone = h("div", { class: "bz-consigne" }, champ, h("div", { class: "btn-row" }, ok, fermer), err);
  ok.addEventListener("click", () => busy(ok, o.occupe, async () => {
    const text = champ.value.trim();
    if (o.obligatoire && !text) { err.textContent = o.obligatoire; return; }
    err.textContent = "";
    try { await o.envoyer(text); zone.remove(); } catch (e) { err.textContent = e.message; }
  }));
  fermer.addEventListener("click", () => zone.remove());
  champ.addEventListener("keydown", (e) => { if (e.key === "Escape") zone.remove(); });
  conteneur.querySelectorAll(".bz-consigne").forEach((z) => z.remove());
  apres.after(zone);
  champ.focus();
  return zone;
}
