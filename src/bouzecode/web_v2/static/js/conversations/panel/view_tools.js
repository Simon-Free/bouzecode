// [desc] Barre d'outils commune aux vues Récap / Fichiers modifiés / Coûts & tours : bouton « Actualiser » occupé pendant le rechargement. [/desc]

import { busy, h } from "../../lib/ui.js";

export function refreshButton(label, fn) {
  const b = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, label);
  b.addEventListener("click", () => busy(b, "Actualisation…", fn));
  return b;
}
