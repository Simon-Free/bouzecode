// Un tour à la loupe : rupture du préfixe, éléments du payload (tokens, cache, diff), réponse du modèle.
import { h, api, skeleton, failed, toast } from "../lib/ui.js";
import { etat, url, chargerTour, nombre, LIBELLES_CACHE, naviguer } from "./etat.js";
import { rendreReponse } from "./reponse.js";

function etatDiff(detail, e) {
  const d = detail.diff;
  if (d.premier_tour) return "";
  if (d.ajoutes.includes(e.indice)) return "ajouté";
  const m = d.modifies.find((x) => x.indice === e.indice);
  if (!m) return "inchangé";
  return m.nature === "ajout_en_fin" ? `+${nombre(m.ajoutes)} car. en fin` : "modifié";
}

function explicationRupture(detail) {
  const d = detail.diff;
  if (d.premier_tour) return "Premier tour : tout est envoyé et écrit au cache.";
  if (d.rupture == null) return "Rien n'a changé par rapport au tour précédent : le préfixe est intact.";
  const e = detail.elements[d.rupture];
  const m = d.modifies.find((x) => x.indice === d.rupture);
  const quoi = !m ? "est nouveau" : m.nature === "ajout_en_fin"
    ? `a reçu ${nombre(m.ajoutes)} caractères en fin` : `a changé à la position ${nombre(m.position)}`;
  return `Le préfixe casse à l'élément #${e.indice} (${e.libelle.slice(0, 70)}), qui ${quoi} : `
    + "tout ce qui le suit est relu au plein tarif ou réécrit dans le cache.";
}

function causeDuRate(detail) {
  if (!detail.cause_cache) return null;
  return h("p", { class: "eq-cause" }, h("strong", {}, "Cache raté — cause probable : "), detail.cause_cache);
}

function resume(detail) {
  const a = detail.api;
  const cases = [["Plein tarif", a.api_input_tokens], ["Cache lu", a.api_cache_read],
    ["Écrit au cache", a.api_cache_create], ["Sortie", a.api_output_tokens]];
  return h("div", { class: "eq-api" }, cases.map(([l, v]) =>
    h("div", { class: "eq-api__case" }, h("span", { class: "eq-api__v" }, nombre(v)), h("span", { class: "eq-api__l" }, l))));
}

async function deplier(detail, e, zone) {
  if (!e.tronque) { zone.textContent = e.apercu; return; }
  zone.textContent = "Chargement du texte intégral…";
  try {
    const complet = await api("GET", url(`/tours/${detail.tour}/elements/${e.indice}`));
    zone.textContent = complet.texte;
  } catch (err) {
    zone.textContent = e.apercu;
    toast.err(`Texte intégral indisponible : ${err.message}`);
  }
}

function modification(detail, e) {
  const m = detail.diff.modifies.find((x) => x.indice === e.indice);
  if (!m || m.nature !== "modifie") return null;
  return h("div", { class: "eq-modif" },
    h("div", {}, `Change à la position ${nombre(m.position)} (écart de taille ${nombre(m.ecart_taille)} car.)`),
    h("pre", { class: "eq-pre eq-pre--avant" }, m.avant), h("pre", { class: "eq-pre eq-pre--apres" }, m.apres));
}

function element(detail, e) {
  const zone = h("pre", { class: "eq-pre" });
  const bloc = h("details", {
    class: "eq-el", id: `element-${e.indice}`, "data-rupture": detail.diff.rupture === e.indice ? "1" : null,
    ontoggle: (ev) => { if (ev.target.open && !zone.textContent) deplier(detail, e, zone); },
  },
  h("summary", { class: "eq-el__tete" },
    h("span", { class: "eq-el__num" }, `#${e.indice}`),
    h("span", { class: "eq-el__lib" }, e.libelle || e.genre),
    h("span", { class: "eq-el__diff" }, etatDiff(detail, e)),
    h("span", { class: "eq-el__cache", "data-cache": e.cache }, LIBELLES_CACHE[e.cache] || e.cache),
    h("span", { class: "eq-el__tok" }, `${nombre(e.tokens)} tk`)),
  modification(detail, e), zone);
  return bloc;
}

function retires(detail) {
  const r = detail.diff.retires;
  if (!r.length) return null;
  return h("div", { class: "eq-retires" }, h("h3", {}, `Retirés depuis le tour précédent (${r.length})`),
    h("ul", {}, r.map((x) => h("li", {}, `${x.libelle} — ${nombre(x.tokens)} tk`))));
}

function outils(detail) {
  const permalien = () => {
    const lien = `${location.origin}${location.pathname}#tour-${detail.tour}`;
    navigator.clipboard.writeText(lien).then(() => toast.ok("Lien du tour copié."),
      () => toast.err("Copie refusée par le navigateur."));
  };
  return h("div", { class: "btn-row eq-tour__outils" },
    h("button", { type: "button", class: "btn btn--ghost btn--sm", disabled: detail.precedent == null,
      onclick: () => naviguer(`#tour-${detail.precedent}`) }, "← Précédent"),
    h("button", { type: "button", class: "btn btn--ghost btn--sm", disabled: detail.suivant == null,
      onclick: () => naviguer(`#tour-${detail.suivant}`) }, "Suivant →"),
    h("button", { type: "button", class: "btn btn--ghost btn--sm", onclick: permalien }, "Copier le lien"),
    h("a", { class: "btn btn--ghost btn--sm", href: url(`/tours/${detail.tour}/export`) }, "Exporter le JSON"));
}

function rendre(detail, zone) {
  zone.removeAttribute("aria-busy");
  //  replaceChildren écrit « null » en texte pour une section absente (pas de cause de cache,
  //  rien de retiré, pas de réponse) : les sections vides sont écartées.
  zone.replaceChildren(...[
    h("div", { class: "eq-tour__tete" }, h("h2", {}, `Tour ${detail.tour}`), outils(detail)),
    resume(detail), causeDuRate(detail),
    h("p", { class: "eq-rupture", "data-premier": detail.diff.premier_tour ? "1" : null }, explicationRupture(detail)),
    h("h3", {}, `Ce qui a été envoyé (${detail.elements.length} éléments)`),
    h("div", { class: "eq-elements" }, detail.elements.map((e) => element(detail, e))),
    retires(detail), rendreReponse(detail)].filter((el) => el != null && el !== ""));
}

function surligner(indice) {
  const el = indice == null ? null : document.getElementById(`element-${indice}`);
  if (!el) return;
  el.open = true;
  el.scrollIntoView({ block: "center" });
  el.classList.add("is-highlighted");
  setTimeout(() => el.classList.remove("is-highlighted"), 2000);
}

export async function afficherTour(n, indice) {
  const zone = document.getElementById("eq-tour");
  if (!etat.details.has(n)) skeleton(zone, 8);
  try {
    const detail = await chargerTour(n);
    if (etat.tour !== n) return;   // réponse tardive : l'utilisateur est déjà sur un autre tour
    rendre(detail, zone);
    surligner(indice);
  } catch (err) {
    if (etat.tour !== n) return;
    failed(zone, err, () => afficherTour(n, indice), { title: `Impossible de charger le tour ${n}.` });
  }
}
