// [desc] Rendu markdown SÛR et minimal (titres, listes, code, gras, code en ligne, paragraphes) : construit des nœuds DOM, jamais d'innerHTML. [/desc]
//
// Sert au texte des plans d'agents dans « À traiter ». Tout le texte passe par des nœuds texte :
// un plan qui contient du HTML l'affiche tel quel, il ne l'interprète pas.

import { h } from "../lib/ui.js";

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/;

function enLigne(texte) {
  return texte.split(INLINE).filter(Boolean).map((morceau) => {
    if (morceau.startsWith("`") && morceau.endsWith("`") && morceau.length > 2) return h("code", null, morceau.slice(1, -1));
    if (morceau.startsWith("**") && morceau.endsWith("**") && morceau.length > 4) return h("strong", null, morceau.slice(2, -2));
    return document.createTextNode(morceau);
  });
}

function typeDeLigne(ligne) {
  if (/^```/.test(ligne)) return "code";
  if (/^#{1,6}\s/.test(ligne)) return "titre";
  if (/^\s*[-*]\s+/.test(ligne)) return "ul";
  if (/^\s*\d+[.)]\s+/.test(ligne)) return "ol";
  if (!ligne.trim()) return "vide";
  return "texte";
}

function blocCode(lignes, i) {
  const contenu = [];
  let j = i + 1;
  while (j < lignes.length && !/^```/.test(lignes[j])) contenu.push(lignes[j++]);
  return { el: h("pre", { class: "bz-md__code" }, h("code", null, contenu.join("\n"))), suite: j + 1 };
}

function blocListe(lignes, i, type) {
  const items = [];
  let j = i;
  while (j < lignes.length && typeDeLigne(lignes[j]) === type) {
    items.push(h("li", null, enLigne(lignes[j].replace(/^\s*(?:[-*]|\d+[.)])\s+/, ""))));
    j += 1;
  }
  return { el: h(type, null, items), suite: j };
}

function blocParagraphe(lignes, i) {
  const texte = [];
  let j = i;
  while (j < lignes.length && typeDeLigne(lignes[j]) === "texte") texte.push(lignes[j++].trim());
  return { el: h("p", null, enLigne(texte.join(" "))), suite: j };
}

/** Rend `texte` (markdown) en un élément `.bz-md`. */
export function rendreMarkdown(texte) {
  const lignes = String(texte || "").replace(/\r\n?/g, "\n").split("\n");
  const racine = h("div", { class: "bz-md" });
  let i = 0;
  while (i < lignes.length) {
    const type = typeDeLigne(lignes[i]);
    let bloc;
    if (type === "vide") { i += 1; continue; }
    if (type === "code") bloc = blocCode(lignes, i);
    else if (type === "titre") bloc = { el: h("h4", { class: "bz-md__titre" }, enLigne(lignes[i].replace(/^#+\s+/, ""))), suite: i + 1 };
    else if (type === "ul" || type === "ol") bloc = blocListe(lignes, i, type);
    else bloc = blocParagraphe(lignes, i);
    racine.appendChild(bloc.el);
    i = bloc.suite;
  }
  return racine;
}
