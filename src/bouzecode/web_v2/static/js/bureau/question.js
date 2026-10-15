// [desc] Bloc « question d'agent » réutilisable (boîte À traiter, tâche dépliée, assistant) : options cliquables + réponse libre, verrouillage au premier clic, erreur inline. [/desc]
//
// R1/R5 : au premier clic (option OU Répondre) TOUT le bloc se verrouille, le bouton cliqué
// passe occupé ; une option n'écrase jamais le brouillon tapé dans le champ libre.
// R3 : succès → le bloc affiche « Réponse envoyée : … — l'agent reprend ». R4 : échec →
// déverrouillé, erreur sous le bloc, texte conservé.

import { h, busy } from "../lib/ui.js";

function libelleOption(o) {
  if (!o) return "";
  if (typeof o === "string") return o;
  return o.label || o.titre || "";
}

function verrouiller(bloc, verrou, sauf) {
  bloc.racine.dataset.locked = verrou ? "true" : "false";
  for (const b of bloc.boutons) if (b !== sauf) b.disabled = verrou;
  if (bloc.champ) bloc.champ.readOnly = verrou;
}

function confirmer(racine, texte) {
  racine.replaceChildren(h("p", { class: "bz-q__ok", role: "status" },
    h("span", { class: "badge", "data-tone": "info" }, "✓ Réponse envoyée"),
    " ", h("span", { class: "bz-q__echo" }, `« ${texte} »`), " — l'agent reprend…"));
  racine.dataset.done = "true";
}

async function soumettre(bloc, bouton, texte) {
  if (!texte || bloc.racine.dataset.locked === "true") return;
  verrouiller(bloc, true, bouton);
  bloc.erreur.textContent = "";
  try {
    await busy(bouton, "Envoi…", () => bloc.repondre(texte));
    confirmer(bloc.racine, texte);
  } catch (e) {
    verrouiller(bloc, false);
    bloc.erreur.textContent = `Réponse non transmise : ${e.message}`;
  }
}

function zoneOptions(bloc, options) {
  const zone = h("div", { class: "bz-q__options", role: "group", "aria-label": "Réponses proposées" });
  for (const o of options) {
    const label = libelleOption(o);
    if (!label) continue;
    const desc = o && typeof o === "object" ? (o.description || "") : "";
    const b = h("button", { type: "button", class: "btn btn--sm bz-q__opt", title: desc || null }, label);
    b.addEventListener("click", () => soumettre(bloc, b, label));
    bloc.boutons.push(b);
    zone.appendChild(b);
  }
  return zone;
}

function zoneLibre(bloc, avecOptions) {
  const champ = h("textarea", { class: "textarea bz-q__libre", rows: "2", "aria-label": "Réponse libre",
    placeholder: avecOptions ? "…ou écris ta propre réponse" : "Ta réponse…" });
  const envoyer = h("button", { type: "button", class: "btn btn--primary btn--sm" }, "Répondre");
  bloc.champ = champ;
  bloc.boutons.push(envoyer);
  envoyer.addEventListener("click", () => soumettre(bloc, envoyer, champ.value.trim()));
  champ.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    soumettre(bloc, envoyer, champ.value.trim());
  });
  return h("div", { class: "bz-q__libre-row" }, champ, envoyer);
}

/**
 * @param {{texte:string, options?:Array, allow_freetext?:boolean}} q
 * @param {(texte:string)=>Promise<any>} repondre  appel réseau ; lève en cas d'échec
 * @returns {HTMLElement} le bloc (porte `dataset.signature` pour éviter les redessins inutiles)
 */
export function blocQuestion(q, repondre) {
  const options = Array.isArray(q.options) ? q.options : [];
  const racine = h("div", { class: "bz-q" });
  const bloc = { racine, repondre, boutons: [], champ: null, erreur: h("p", { class: "field__error bz-q__erreur", role: "alert" }) };
  racine.dataset.signature = signatureQuestion(q);
  racine.appendChild(h("p", { class: "bz-q__texte" }, q.texte || q.question || "L'agent attend ta réponse."));
  if (options.length) racine.appendChild(zoneOptions(bloc, options));
  if (q.allow_freetext !== false) racine.appendChild(zoneLibre(bloc, options.length > 0));
  racine.appendChild(bloc.erreur);
  return racine;
}

export function signatureQuestion(q) {
  return JSON.stringify([q.texte || q.question || "", (q.options || []).map(libelleOption)]);
}
