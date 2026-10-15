// Ce qui sature le contexte : aire empilée par catégorie au fil des tours + 20 plus gros morceaux.
import { h, api, skeleton, failed } from "../lib/ui.js";
import { url, nombre, kilo, naviguer } from "./etat.js";
import { aireEmpilee } from "./svg.js";

function legende(d) {
  return h("div", { class: "eq-legende eq-legende--satur" }, d.categories.map((c) =>
    h("span", { class: `eq-l eq-l--${c}` }, d.libelles[c] || c)));
}

function plusGros(d) {
  const total = d.series.find((s) => s.tour === d.tour) || {};
  const somme = d.categories.reduce((a, c) => a + (total[c] || 0), 0) || 1;
  return h("table", { class: "eq-table" },
    h("caption", {}, `Les 20 plus gros morceaux du tour ${d.tour}`),
    h("thead", {}, h("tr", {}, h("th", {}, "Morceau"), h("th", {}, "Tokens"), h("th", {}, "Part"))),
    h("tbody", {}, d.plus_gros.map((m) => h("tr", {},
      h("td", {}, h("a", { href: `#tour-${d.tour}/element-${m.indice}` }, m.libelle)),
      h("td", { class: "eq-num" }, nombre(m.tokens)),
      h("td", { class: "eq-num" }, `${Math.round((100 * m.tokens) / somme)} %`)))));
}

export async function afficherSaturation(tour) {
  const vue = document.getElementById("vue-saturation");
  skeleton(vue, 6);
  try {
    const q = tour != null ? `?tour=${tour}` : "";
    const d = await api("GET", url(`/saturation${q}`));
    const graphe = aireEmpilee(d.series, d.categories, {
      titre: "Composition du contexte (tokens estimés) par tour", format: kilo,
      surClic: (t) => naviguer(`#saturation-${t}`),
    });
    vue.replaceChildren(
      h("p", { class: "eq-intro" }, "Clique sur le graphique pour détailler un tour. La note est découpée en prose et en extraits de code (sections « snippet »)."),
      legende(d), graphe, plusGros(d));
  } catch (err) {
    failed(vue, err, () => afficherSaturation(tour));
  }
}
