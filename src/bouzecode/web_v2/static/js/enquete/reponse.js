// Ce que le modèle a répondu au tour : réflexion, texte, appels d'outils (entrées) et leurs résultats,
// plus les appels annexes du tour.
import { h } from "../lib/ui.js";
import { nombre } from "./etat.js";

function appel(a) {
  return h("details", { class: "eq-appel" },
    h("summary", {}, h("span", { class: "eq-appel__nom" }, a.nom), " ",
      h("span", { class: "eq-appel__id" }, a.id)),
    h("pre", { class: "eq-pre" }, JSON.stringify(a.entree, null, 2)));
}

function resultat(r) {
  return h("details", { class: "eq-appel" },
    h("summary", {}, h("span", { class: "eq-appel__nom" }, `↩ ${r.nom}`), " ",
      h("span", { class: "eq-appel__id" }, `${nombre(r.taille)} car.${r.tronque ? " (aperçu)" : ""}`)),
    h("pre", { class: "eq-pre" }, r.texte));
}

function annexes(liste) {
  if (!liste || !liste.length) return null;
  return h("div", { class: "eq-annexes" }, h("h4", {}, `Appels annexes (${liste.length})`),
    h("ul", {}, liste.map((a) => h("li", {},
      `${a.label || "appel annexe"} · ${a.model || "?"} · entrée ${nombre(a.api_input_tokens)} · sortie ${nombre(a.api_output_tokens)}`))));
}

export function rendreReponse(detail) {
  const r = detail.reponse;
  const bloc = h("section", { class: "eq-reponse" }, h("h3", {}, "Réponse du modèle"));
  if (!r) {
    bloc.appendChild(h("p", { class: "eq-muet" }, "Réponse introuvable dans la session."));
    return bloc;
  }
  if (r.reflexion) {
    bloc.appendChild(h("details", { class: "eq-appel" }, h("summary", {}, "Réflexion"),
      h("pre", { class: "eq-pre" }, r.reflexion)));
  }
  if (r.texte && r.texte.trim() && r.texte.trim() !== ".") bloc.appendChild(h("pre", { class: "eq-pre eq-texte" }, r.texte));
  if (r.appels.length) bloc.appendChild(h("h4", {}, `Appels d'outils (${r.appels.length})`));
  r.appels.forEach((a) => bloc.appendChild(appel(a)));
  if (r.resultats.length) bloc.appendChild(h("h4", {}, `Résultats (${r.resultats.length})`));
  r.resultats.forEach((x) => bloc.appendChild(resultat(x)));
  const ann = annexes(detail.annexes);
  if (ann) bloc.appendChild(ann);
  return bloc;
}
