// [desc] Menu ⋯ d'une tâche : « Marquer faite… », « Doublon de… », « Caduque… » — un dialogue (tâche liée, commentaire), puis toast avec Annuler (= Rouvrir). Refusé proprement si un agent travaille sur la tâche. [/desc]

import { h, busy, toast } from "../lib/ui.js";
import { toutesLesTaches } from "./store.js";
import { teteClassement } from "./classement.js";
import * as act from "./actions.js";

const MOTIFS = {
  faite: { titre: "Marquer faite…", bouton: "Marquer faite", lien: "Fait par la tâche (optionnel)",
    aide: "Le travail a été fait ailleurs : dis où (tâche, tour, commit)." },
  doublon: { titre: "Doublon de…", bouton: "Marquer doublon", lien: "Doublon de la tâche",
    aide: "Choisis la tâche que tu gardes : c'est elle qui porte le travail." },
  caduque: { titre: "Caduque…", bouton: "Marquer caduque", lien: "",
    aide: "Elle n'a plus d'objet : dis pourquoi." },
};

const CLASSEES = new Set(["faite", "abandonnee"]);
const court = (s, n = 70) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** Les tâches qu'on peut désigner : celles du même chantier d'abord, jamais elle-même. */
function candidates(t) {
  const autres = toutesLesTaches().filter((x) => x.id !== t.id);
  const rang = (x) => ((x.macro_id || "") === (t.macro_id || "") ? 0 : 1) + (CLASSEES.has(x.statut_ui) ? 2 : 0);
  return autres.sort((a, b) => rang(a) - rang(b));
}

function selectTaches(t, obligatoire) {
  const sel = h("select", { class: "select", "data-role": "lien" },
    h("option", { value: "" }, obligatoire ? "— choisis la tâche —" : "— aucune —"));
  for (const x of candidates(t)) {
    sel.appendChild(h("option", { value: x.id }, `${court(x.titre || "Sans titre")} · ${x.libelle_statut || x.statut_ui} · ${x.id}`));
  }
  return sel;
}

function champ(label, controle, hint) {
  const id = `bz-c-${Math.random().toString(36).slice(2, 8)}`;
  controle.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), controle,
    hint ? h("span", { class: "field__hint" }, hint) : null, h("span", { class: "field__error" }));
}

function construire(t, motif) {
  const m = MOTIFS[motif];
  const d = { t, motif };
  d.lien = m.lien ? selectTaches(t, motif === "doublon") : null;
  d.commentaire = h("textarea", { class: "textarea", rows: "3", "data-role": "commentaire",
    placeholder: "Où c'est fait, pourquoi… (visible sur la carte)" });
  d.erreur = h("p", { class: "field__error", role: "alert" });
  d.annuler = h("button", { type: "button", class: "btn" }, "Annuler");
  d.valider = h("button", { type: "submit", class: "btn btn--primary", "data-role": "go" }, m.bouton);
  d.fLien = d.lien ? champ(m.lien, d.lien) : null;
  d.form = h("form", { class: "ui-dialog__body bz-classer", method: "dialog" },
    h("h2", { class: "ui-dialog__title", id: "bz-classer-t" }, m.titre),
    h("p", { class: "ui-dialog__text" }, t.titre || ""),
    h("p", { class: "field__hint" }, m.aide),
    d.fLien, champ("Commentaire", d.commentaire), d.erreur,
    h("div", { class: "ui-dialog__actions" }, d.annuler, d.valider));
  d.dlg = h("dialog", { class: "ui-dialog", "aria-labelledby": "bz-classer-t", "data-motif": motif }, d.form);
  return d;
}

/** Le toast du geste : ce qu'est devenue la tâche, avec Annuler (= Rouvrir, historique gardé). */
function annoncer(t, r) {
  const phrase = r.classement ? teteClassement(r.classement) : "Tâche classée";
  toast.ok(`« ${court(t.titre || "Tâche", 50)} » : ${phrase}${act.suffixeArchivage(r)}.`,
    { action: { label: "Annuler", fn: () => act.rouvrirTache(t.id) } });
}

async function soumettre(d, fermer) {
  d.erreur.textContent = "";
  if (d.motif === "doublon" && !d.lien.value) {
    d.erreur.textContent = "Choisis la tâche dont c'est le doublon.";
    d.lien.focus();
    return;
  }
  await busy(d.valider, "Enregistrement…", async () => {
    try {
      const r = await act.classerAvecCommentaire(d.t.id, d.motif,
        { commentaire: d.commentaire.value.trim(), de: d.lien ? d.lien.value : "" });
      fermer();
      annoncer(d.t, r);
      await act.rafraichir();
    } catch (e) {
      d.erreur.textContent = `Non marquée : ${e.message}`;
    }
  });
}

/** Ouvre le dialogue « Marquer faite… / Doublon de… / Caduque… » pour la ligne `t`. */
export function ouvrirClassement(t, motif) {
  const precedent = document.activeElement;
  const d = construire(t, motif);
  const fermer = () => {
    if (d.dlg.open) d.dlg.close();
    d.dlg.remove();
    if (precedent && precedent.isConnected && typeof precedent.focus === "function") precedent.focus();
  };
  d.annuler.addEventListener("click", fermer);
  d.dlg.addEventListener("cancel", (e) => { e.preventDefault(); if (d.valider.getAttribute("aria-busy") !== "true") fermer(); });
  d.form.addEventListener("submit", (e) => { e.preventDefault(); soumettre(d, fermer); });
  document.body.appendChild(d.dlg);
  try { d.dlg.showModal(); } catch (_) { d.dlg.setAttribute("open", ""); }
  (d.lien || d.commentaire).focus();
  return d.dlg;
}

/** Les trois entrées du menu ⋯ d'une tâche ouverte ; désactivées (avec la raison) si un agent y travaille. */
export function entreesClassement(t) {
  if (CLASSEES.has(t.statut_ui)) return [];
  const occupe = !!t.agent_actif;
  const hint = occupe ? "Un agent travaille sur cette tâche : arrête-le ou attends sa livraison." : null;
  return ["sep", ...Object.entries(MOTIFS).map(([motif, m]) => ({
    label: m.titre, disabled: occupe, hint, fn: () => ouvrirClassement(t, motif) }))];
}
