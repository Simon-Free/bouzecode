// [desc] Sections de chantier du Bureau (mode Chantier) : registre persistant, en-tête, archives repliables ; zone « + Ajouter une tâche » (aussi utilisée par le mode Statut, avec choix du chantier). Le glisser-déposer est dans glisser.js. [/desc]

import { h, lock, toast, highlight } from "../lib/ui.js";
import { state, savePrefs, demanderRendu, basculerArchives } from "./store.js";
import { registre } from "./tache.js";
import { enteteChantier } from "./chantier.js";
import * as act from "./actions.js";

const sections = new Map(); // id ("" = sans chantier) -> {el, head, corps, archives, ajout, sigHead}

// ---------------------------------------------------------------- zone d'ajout

async function creerDepuisZone(champ, err, macroId, texte) {
  try {
    // Un seul champ : tout le texte va dans le brief ; le serveur en tire le titre (1re ligne).
    const r = await act.creerTache({ corps: texte, macro_id: macroId });
    const id = r && r.micro && r.micro.id;
    champ.value = "";
    champ.dispatchEvent(new Event("input"));
    if (id) { state.deplies.add(id); savePrefs(); }
    toast.ok(state.mode === "statut" ? "Tâche créée — dans « À lancer »." : "Tâche créée.");
    await act.rafraichir();
    const rec = id && registre.get(id);
    if (!rec) return;
    highlight(rec.el);
    const brief = rec.el.querySelector(".bz-ed__brief");
    if (brief) brief.focus();
  } catch (ex) { err.textContent = `Création impossible : ${ex.message}`; }
}

/** Liste « dans le chantier… » de la zone d'ajout du mode Statut (chantiers actifs + Sans chantier). */
function choixChantier() {
  const sel = h("select", { class: "select bz-add__chantier", "aria-label": "Chantier de la nouvelle tâche" });
  const remplir = () => {
    const actifs = ((state.lignes && state.lignes.chantiers) || []).filter((c) => c.etat === "active" || c.etat === "en_pause");
    const sig = JSON.stringify(actifs.map((c) => [c.macro_id, c.titre]));
    if (sel.dataset.sig === sig) return;
    const garde = sel.value;
    sel.dataset.sig = sig;
    sel.replaceChildren(h("option", { value: "" }, "Sans chantier"), ...actifs.map((c) => h("option", { value: c.macro_id }, c.titre)));
    sel.value = actifs.some((c) => c.macro_id === garde) ? garde : "";
  };
  return { sel, remplir };
}

/** « + Ajouter une tâche… » : Entrée crée (1re ligne = titre, reste = brief), Échap vide.
 *  `macroId` fixe le chantier ; `null` = le choisir dans une liste (mode Statut). */
export function zoneAjout(macroId) {
  const choix = macroId === null ? choixChantier() : null;
  const champ = h("textarea", { class: "textarea bz-add__input", rows: "1",
    "aria-label": "Ajouter une tâche", placeholder: "+ Ajouter une tâche… (Entrée)",
    title: "Entrée pour ajouter, Maj+Entrée pour une nouvelle ligne" });
  const err = h("p", { class: "field__error", role: "alert" });
  const grandir = () => { champ.style.height = "auto"; champ.style.height = `${Math.min(champ.scrollHeight, 240)}px`; };
  champ.addEventListener("input", grandir);
  champ.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { champ.value = ""; grandir(); err.textContent = ""; return; }
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    const texte = champ.value.trim();
    if (!texte) { err.textContent = "Écris d'abord la tâche : sa 1re ligne lui sert de titre."; return; }
    err.textContent = "";
    await lock(champ, () => creerDepuisZone(champ, err, choix ? choix.sel.value : macroId, texte));
  });
  const el = h("div", { class: "bz-add" }, choix ? h("div", { class: "bz-add__row" }, champ, choix.sel) : champ, err);
  if (choix) { el.majChoix = choix.remplir; choix.remplir(); }
  return el;
}

// ---------------------------------------------------------------- section

/** Bloc « ▸ N archivée(s) » en bas d'un chantier : replié par défaut, ouvert à la demande. */
function blocArchives(id) {
  const btn = h("button", { type: "button", class: "btn btn--ghost btn--sm bz-arch__btn", "aria-expanded": "false" });
  const corps = h("div", { class: "bz-arch__corps" });
  btn.addEventListener("click", () => basculerArchives(id || "__sans"));
  return { el: h("div", { class: "bz-arch" }, btn, corps), btn, corps };
}

/** La section d'un chantier (créée une fois, puis réutilisée d'un rendu à l'autre). */
export function section(id) {
  let s = sections.get(id);
  if (s) return s;
  const el = h("section", { class: "bz-ch", "data-chantier": id || "sans" });
  const corps = h("div", { class: "bz-ch__corps" });
  const archives = blocArchives(id);
  const ajout = zoneAjout(id);
  el.append(corps, ajout, archives.el);
  s = { el, head: null, corps, archives, ajout, sigHead: "" };
  sections.set(id, s);
  return s;
}

function basculerRepli(id) {
  if (state.replies.has(id)) state.replies.delete(id); else state.replies.add(id);
  savePrefs();
  demanderRendu();
}

/** Aide de la section des tâches ORPHELINES : ce qu'elles sont, et le geste qui les range
 *  (poignée ⠿ : glisser vers un chantier, ou clic → « Déplacer vers… »). Pas de bouton de plus. */
export const AIDE_SANS_CHANTIER = "Rattachées à aucun chantier. Pour en ranger une : glisse sa poignée ⠿ "
  + "sur un chantier, ou clique la poignée pour choisir.";

function enteteSansChantier(s) {
  if (s.head) return;
  const titre = (state.lignes && state.lignes.titre_non_rattachees) || "Sans chantier";
  s.aide = h("p", { class: "bz-muted bz-ch__aide" }, AIDE_SANS_CHANTIER);
  s.head = h("header", { class: "bz-ch__head bz-ch__head--sans" }, h("span", { class: "bz-ch__titre bz-ch__titre--static" }, titre));
  s.el.prepend(s.head, s.aide);
}

/** Met l'en-tête à jour s'il a changé — pas pendant un renommage, et le focus du titre est gardé. */
export function majEntete(s, id, c) {
  if (!c) { enteteSansChantier(s); return; }
  const sig = JSON.stringify([c.titre, c.etat, c.projets, c.compte_ui, state.replies.has(c.macro_id)]);
  const actif = document.activeElement;
  const dansTete = s.head && s.head.contains(actif);
  if (sig === s.sigHead || (dansTete && actif.tagName === "INPUT")) return;
  const head = enteteChantier(c, { replie: state.replies.has(id), onToggle: () => basculerRepli(id) });
  const focusTitre = dansTete && actif.classList.contains("bz-ch__titre");
  if (s.head) s.head.replaceWith(head); else s.el.prepend(head);
  s.head = head;
  s.sigHead = sig;
  if (focusTitre) head.querySelector(".bz-ch__titre").focus();
}
