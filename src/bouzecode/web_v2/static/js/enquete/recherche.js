// Recherche plein texte dans toute la session ; chaque résultat mène au tour (et à l'élément).
import { h, api, skeleton, failed, empty } from "../lib/ui.js";
import { url } from "./etat.js";

const LIEUX = { note: "note", payload: "envoyé", reponse: "réponse" };

function lien(r) {
  const cible = r.ou === "note" ? "#note" : `#tour-${r.tour}${r.indice != null ? `/element-${r.indice}` : ""}`;
  const lieu = LIEUX[r.ou] || r.ou.replace("resultat:", "résultat ");
  return h("li", { class: "eq-res" }, h("a", { href: cible },
    h("span", { class: "eq-res__tour" }, `Tour ${r.tour}`),
    h("span", { class: "eq-res__lieu" }, lieu),
    h("span", { class: "eq-res__extrait" }, r.extrait)));
}

export async function rechercher(q) {
  const vue = document.getElementById("vue-recherche");
  skeleton(vue, 5);
  try {
    const d = await api("GET", url(`/recherche?q=${encodeURIComponent(q)}`));
    if (!d.resultats.length) {
      empty(vue, { title: `Aucun résultat pour « ${q} ».`, text: "La recherche porte sur la note, ce qui a été envoyé et les réponses." });
      return;
    }
    vue.replaceChildren(
      h("p", { class: "eq-intro" }, `${d.resultats.length} résultat(s) pour « ${d.q} »${d.limite_atteinte ? " (limite atteinte, précise ta recherche)" : ""}.`),
      h("ol", { class: "eq-resultats" }, d.resultats.map(lien)));
  } catch (err) {
    failed(vue, err, () => rechercher(q));
  }
}
