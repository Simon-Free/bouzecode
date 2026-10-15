// [desc] Chantiers du Bureau (SPEC §4.4) : en-tête (titre, dépôts, compteurs, menu ⋯ clavier), renommer, décrire, dépôts, pause, monter/descendre, archiver, supprimer ; création d'un chantier. [/desc]

import { h, busy, lock, toast, confirm as demander, dirty, menu, highlight, api } from "../lib/ui.js";
import { openReposDialog } from "../projects_admin.js";
import { state, savePrefs, nomProjet, chantierParId } from "./store.js";
import { rendreGlissable } from "./glisser.js";
import * as act from "./actions.js";
import { TASK_STATUSES } from "../lib/states.js";

export const ARCHIVES = ["terminee", "abandonnee"];

/** Compteurs de l'en-tête, dans l'ordre d'urgence : les MOTS du lexique unique (même mot que
 *  le badge des tâches), en minuscules — « 3 à décider · 1 à vérifier · 7 à lancer ». */
const COMPTES = ["a_repondre", "a_decider", "en_echec", "a_relire", "en_cours", "brouillon"];

function resumeComptes(c) {
  const cu = c.compte_ui || {};
  return COMPTES.filter((k) => cu[k]).map((k) => `${cu[k]} ${TASK_STATUSES[k].label.toLowerCase()}`).join(" · ");
}

/** En-tête d'un chantier (reconstruit à chaque rendu : pas de champ éditable dedans hors édition). */
export function enteteChantier(c, { replie, onToggle }) {
  const archive = ARCHIVES.includes(c.etat);
  const titre = h("button", { type: "button", class: "bz-ch__titre", "aria-expanded": replie ? "false" : "true",
    title: replie ? "Déplier" : "Replier" },
  h("span", { class: "bz-ch__caret", "aria-hidden": "true" }, replie ? "▸" : "▾"), c.titre);
  titre.addEventListener("click", onToggle);
  const etat = c.etat === "en_pause" ? h("span", { class: "badge", "data-tone": "neutral" }, "⏸ En pause")
    : archive ? h("span", { class: "badge", "data-tone": "neutral" }, "▪ Archivé") : null;
  const depots = h("span", { class: "bz-ch__depots" },
    (c.projets || []).map((s) => h("span", { class: "chip" }, nomProjet(s))));
  const plus = h("button", { type: "button", class: "btn btn--ghost btn--sm btn--icon bz-ch__menu",
    "aria-label": `Actions du chantier ${c.titre}` }, "⋯");
  const grip = archive ? null : poigneeChantier(c);
  const head = h("header", { class: "bz-ch__head" }, grip, titre, etat, depots,
    h("span", { class: "bz-ch__comptes" }, resumeComptes(c)), h("span", { class: "menu" }, plus));
  menu(plus, () => itemsMenu(c, head));
  return head;
}

function itemsMenu(c, head) {
  const archive = ARCHIVES.includes(c.etat);
  const ordre = ((state.lignes && state.lignes.chantiers) || []).map((x) => x.macro_id);
  const i = ordre.indexOf(c.macro_id);
  return [
    { label: "Renommer…", fn: () => renommer(c, head) },
    { label: "Décrire…", fn: () => decrire(c, head) },
    { label: "Dépôts…", fn: () => depots(c) },
    "sep",
    { label: "Monter", disabled: i <= 0, fn: () => deplacer(c, -1) },
    { label: "Descendre", disabled: i < 0 || i >= ordre.length - 1, fn: () => deplacer(c, 1) },
    "sep",
    c.etat === "en_pause"
      ? { label: "Reprendre", fn: () => etat(c, "active", "Chantier repris.") }
      : { label: "Mettre en pause", disabled: archive, fn: () => etat(c, "en_pause", "Chantier en pause.") },
    archive
      ? { label: "Réactiver", fn: () => etat(c, "active", "Chantier réactivé.") }
      : { label: "Archiver", fn: () => etat(c, "terminee", "Chantier archivé (visible dans Archivées).", true) },
    { label: "Supprimer…", danger: true, fn: () => supprimer(c) },
  ];
}

async function etat(c, valeur, message, annulable) {
  await act.modifierChantier(c.macro_id, { etat: valeur });
  toast.ok(message, annulable ? { action: { label: "Annuler", fn: async () => {
    await act.modifierChantier(c.macro_id, { etat: c.etat || "active" });
    toast.ok("Chantier rétabli.");
    await act.rafraichir();
  } } } : undefined);
  await act.rafraichir();
}

const ordreActuel = () => ((state.lignes && state.lignes.chantiers) || []).map((x) => x.macro_id);
const sectionDe = (id) => document.querySelector(`.bz-ch[data-chantier="${CSS.escape(id)}"]`);

/** Envoie un nouvel ordre ; la section du chantier déplacé est occupée pendant l'appel, puis
 *  surlignée à sa nouvelle place, avec « Annuler » dans le toast (R3/R6). Lève en cas d'échec. */
async function appliquerOrdre(id, ordre, message) {
  const avant = ordreActuel();
  const s = sectionDe(id);
  if (s) { s.classList.add("is-saving"); s.setAttribute("aria-busy", "true"); }
  try {
    await act.reordonnerChantiers(ordre);
    await act.rafraichir();
  } finally {
    if (s) { s.classList.remove("is-saving"); s.removeAttribute("aria-busy"); }
  }
  toast.ok(message, { timeout: 10000, action: { label: "Annuler", fn: async () => {
    await act.reordonnerChantiers(avant);
    toast.ok("Ordre des chantiers rétabli.");
    await act.rafraichir();
  } } });
  const apres = sectionDe(id);
  if (apres) highlight(apres.querySelector(".bz-ch__head") || apres);
}

async function deplacer(c, delta) {
  const ordre = ordreActuel();
  const i = ordre.indexOf(c.macro_id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= ordre.length) return;
  [ordre[i], ordre[j]] = [ordre[j], ordre[i]];
  await appliquerOrdre(c.macro_id, ordre, delta < 0 ? "Chantier monté." : "Chantier descendu.");
}

/** Pose le chantier `id` avant (ou après, `apres`) le chantier `cibleId`. */
export async function poserChantier(id, cibleId, apres = false) {
  const ordre = ordreActuel().filter((x) => x !== id);
  const k = ordre.indexOf(cibleId);
  if (k < 0) ordre.push(id); else ordre.splice(apres ? k + 1 : k, 0, id);
  if (JSON.stringify(ordre) === JSON.stringify(ordreActuel())) { toast.info("Le chantier est déjà à cette place."); return; }
  try {
    await appliquerOrdre(id, ordre, `Chantier « ${(chantierParId(id) || {}).titre || ""} » déplacé.`);
  } catch (e) {
    toast.err(`Déplacement impossible : ${e.message}`, { action: { label: "Réessayer", fn: () => poserChantier(id, cibleId, apres) } });
  }
}

/** Dialogue « Déplacer le chantier » : l'alternative sans glisser (clic / Entrée sur la poignée). */
function placerVers(c) {
  const autres = ((state.lignes && state.lignes.chantiers) || [])
    .filter((x) => x.macro_id !== c.macro_id && !ARCHIVES.includes(x.etat));
  const dlg = h("dialog", { class: "ui-dialog", "aria-labelledby": "bz-placer-t" });
  const retour = document.activeElement;
  const fermer = () => { dlg.close(); dlg.remove(); if (retour && retour.isConnected) retour.focus(); };
  const choix = [...autres.map((x) => ({ label: `Avant « ${x.titre} »`, cible: x.macro_id, apres: false })),
    autres.length ? { label: "En dernier", cible: autres[autres.length - 1].macro_id, apres: true } : null].filter(Boolean);
  const liste = h("div", { class: "bz-depots", role: "group", "aria-label": "Places possibles" });
  for (const ch of choix) {
    const b = h("button", { type: "button", class: "btn btn--ghost bz-deplacer__choix" }, ch.label);
    b.addEventListener("click", () => busy(b, "Déplacement…", async () => { await poserChantier(c.macro_id, ch.cible, ch.apres); fermer(); }));
    liste.appendChild(b);
  }
  const annuler = h("button", { type: "button", class: "btn" }, "Annuler");
  annuler.addEventListener("click", fermer);
  dlg.append(h("div", { class: "ui-dialog__body" },
    h("h2", { class: "ui-dialog__title", id: "bz-placer-t" }, "Déplacer le chantier…"),
    h("p", { class: "ui-dialog__text" }, `« ${c.titre} » — ou flèches ↑ ↓ sur la poignée.`), liste),
  h("div", { class: "ui-dialog__actions" }, annuler));
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); fermer(); });
  document.body.appendChild(dlg);
  dlg.showModal();
  (liste.querySelector("button") || annuler).focus();
}

/** Poignée d'un chantier : glisser (souris, doigt), clic / Entrée (dialogue), flèches ↑ ↓ (une place). */
function poigneeChantier(c) {
  const grip = h("button", { type: "button", class: "bz-grip", "aria-label": `Déplacer le chantier ${c.titre}`,
    title: "Glisser pour réordonner (Échap annule) — flèches ↑ ↓ : une place — Entrée : choisir la place" }, "⠿");
  rendreGlissable(grip, { type: "chantier", source: () => grip.closest(".bz-ch"), libelle: () => c.titre,
    surClic: () => placerVers(c), deposer: (cible) => poserChantier(c.macro_id, cible.id, cible.apres) });
  grip.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    busy(grip, null, async () => {
      try { await deplacer(c, e.key === "ArrowUp" ? -1 : 1); } catch (ex) { toast.err(`Déplacement impossible : ${ex.message}`); }
    }).then(() => { const g2 = sectionDe(c.macro_id)?.querySelector(".bz-grip"); if (g2) g2.focus(); });
  });
  return grip;
}

async function supprimer(c) {
  const n = (c.lignes || []).length;
  const ok = await demander({ title: `Supprimer « ${c.titre} » ?`, danger: true, confirmLabel: "Supprimer",
    text: n ? `Ses ${n} tâche(s) iront dans « Sans chantier ». Rien d'autre n'est effacé.`
      : "Le chantier est vide." });
  if (!ok) return;
  const r = await act.supprimerChantier(c.macro_id);
  const detachees = (r && r.detachees) || 0;
  toast.ok(detachees ? `Chantier supprimé : ${detachees} tâche(s) déplacée(s) dans « Sans chantier ».` : "Chantier supprimé.");
  await act.rafraichir();
}

function renommer(c, head) {
  const bouton = head.querySelector(".bz-ch__titre");
  const champ = h("input", { class: "input bz-ch__rename", type: "text", value: c.titre, "aria-label": "Nouveau nom du chantier" });
  const err = h("span", { class: "field__error", role: "alert" });
  bouton.replaceWith(champ);
  champ.after(err);
  champ.focus();
  champ.select();
  let fini = false;
  const fin = () => { fini = true; champ.replaceWith(bouton); err.remove(); bouton.focus(); };
  champ.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { e.preventDefault(); fin(); return; }
    if (e.key !== "Enter") return;
    e.preventDefault();
    const titre = champ.value.trim();
    if (!titre) { err.textContent = "Un chantier a besoin d'un nom."; return; }
    if (titre === c.titre) { fin(); return; }
    await lock(champ, async () => {
      try {
        await act.modifierChantier(c.macro_id, { titre });
        bouton.lastChild.textContent = titre;
        fin();
        toast.ok("Chantier renommé.");
        await act.rafraichir();
      } catch (ex) { err.textContent = `Renommage impossible : ${ex.message}`; }
    });
  });
  champ.addEventListener("blur", () => { if (!fini && champ.value.trim() === c.titre) fin(); });
}

function decrire(c, head) {
  const section = head.parentElement;
  if (section.querySelector(".bz-ch__desc")) { section.querySelector(".bz-ch__desc textarea").focus(); return; }
  const zone = h("textarea", { class: "textarea", rows: "5", "aria-label": `Description du chantier ${c.titre}`,
    placeholder: "Objectif, périmètre, hors périmètre… Rappelé dans le prompt de chaque tâche du chantier." });
  zone.value = c.corps || "";
  const flag = h("span", { class: "dirty-flag" });
  const save = h("button", { type: "button", class: "btn btn--primary btn--sm" }, "Enregistrer");
  const cancel = h("button", { type: "button", class: "btn btn--sm" }, "Fermer");
  const err = h("p", { class: "field__error", role: "alert" });
  const bloc = h("div", { class: "bz-ch__desc" },
    h("div", { class: "field" }, h("label", null, "Description commune ", h("span", { class: "field__hint" }, "— Ctrl+Entrée pour enregistrer")), zone),
    h("div", { class: "btn-row" }, save, cancel, flag), err);
  const d = dirty(bloc, { flag });
  head.after(bloc);
  zone.focus();
  const fermer = async () => {
    if (!(await d.guard())) return;
    d.destroy();
    bloc.remove();
  };
  const enregistrer = () => busy(save, "Enregistrement…", async () => {
    err.textContent = "";
    try {
      await act.modifierChantier(c.macro_id, { corps: zone.value });
      d.markClean();
      d.destroy();
      bloc.remove();
      toast.ok("Description du chantier enregistrée.");
      await act.rafraichir();
    } catch (e) { err.textContent = `Enregistrement impossible : ${e.message}`; }
  });
  save.addEventListener("click", enregistrer);
  cancel.addEventListener("click", fermer);
  bloc.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); enregistrer(); }
    if (e.key === "Escape") { e.preventDefault(); fermer(); }
  });
}

/** Dialogue « Dépôts du chantier » : une case par dépôt enregistré, effet immédiat. */
export function depots(c, dejaChange = false) {
  const actuels = new Set(c.projets || []);
  let changed = dejaChange;
  const dlg = h("dialog", { class: "ui-dialog", "aria-labelledby": "bz-depots-t" });
  const liste = h("div", { class: "bz-depots" });
  if (!state.projets.length) {
    liste.appendChild(h("p", { class: "bz-muted" }, "Aucun dépôt enregistré. Ajoute-en un avec « + Ajouter un dépôt… »."));
  }
  for (const p of state.projets) {
    const box = h("input", { type: "checkbox", value: p.slug, checked: actuels.has(p.slug) });
    const etat = h("span", { class: "bz-muted bz-depots__etat", role: "status" });
    box.addEventListener("change", async () => {
      box.disabled = true;
      etat.textContent = "…";
      try {
        if (box.checked) await act.ajouterDepot(c.macro_id, p.slug);
        else await act.retirerDepot(c.macro_id, p.slug);
        etat.textContent = box.checked ? "ajouté ✓" : "retiré ✓";
        changed = true;
      } catch (e) {
        box.checked = !box.checked;
        etat.textContent = "";
        toast.err(`Dépôt ${p.name || p.slug} : ${e.message}`);
      } finally { box.disabled = false; }
    });
    liste.appendChild(h("label", { class: "bz-depots__item" }, box,
      h("span", null, h("b", null, p.name || p.slug), p.description ? h("span", { class: "bz-muted" }, ` — ${p.description}`) : null), etat));
  }
  const fermer = h("button", { type: "button", class: "btn btn--primary" }, "Terminé");
  const ajouter = h("button", { type: "button", class: "btn", "data-role": "ajouter-depot" }, "+ Ajouter un dépôt…");
  ajouter.addEventListener("click", () => openReposDialog({
    onChange: async () => {
      const res = await api("GET", "/api/projects");
      state.projets = (res && res.projects) || [];
    },
    // Le dépôt créé est rattaché au chantier tout de suite, puis le dialogue se redessine.
    onAdded: async (slug) => {
      try {
        await act.ajouterDepot(c.macro_id, slug);
        c.projets = [...(c.projets || []).filter((s) => s !== slug), slug];
      } catch (e) { toast.err(`Dépôt ${slug} : ${e.message}`); }
      dlg.close(); dlg.remove();
      depots(c, true);
    },
  }));
  dlg.append(h("div", { class: "ui-dialog__body" },
    h("h2", { class: "ui-dialog__title", id: "bz-depots-t" }, `Dépôts de « ${c.titre} »`),
    h("p", { class: "ui-dialog__text" }, "Le premier dépôt coché sert de dépôt par défaut aux tâches du chantier."), liste),
  h("div", { class: "ui-dialog__actions" }, ajouter, fermer));
  document.body.appendChild(dlg);
  const close = async () => { dlg.close(); dlg.remove(); if (changed) await act.rafraichir(); };
  fermer.addEventListener("click", close);
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.showModal();
  (liste.querySelector("input") || fermer).focus();
}

/** Formulaire « + Nouveau chantier » (Entrée crée, champ verrouillé pendant l'appel). */
export function wireNouveauChantier(onCree) {
  const form = document.getElementById("chantier-nouveau");
  const champ = document.getElementById("chantier-titre");
  const err = document.getElementById("chantier-erreur");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const titre = champ.value.trim();
    err.textContent = "";
    if (!titre) { err.textContent = "Donne un nom au chantier."; return; }
    await lock(champ, async () => {
      try {
        const r = await act.creerChantier(titre);
        champ.value = "";
        const id = r && r.macro && (r.macro.id || r.macro.macro_id);
        toast.ok(`Chantier « ${titre} » créé.`);
        if (id) { state.replies.delete(id); savePrefs(); }
        await act.rafraichir();
        if (id) onCree(id);
      } catch (ex) { err.textContent = `Création impossible : ${ex.message}`; }
    });
  });
}

