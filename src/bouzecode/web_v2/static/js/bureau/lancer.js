// [desc] Dialogue Lancer / Relancer une tâche (SPEC §4.7) : dépôt obligatoire, profil, environnement, exécution (local | Rundeck, fichiers non suivis), retour + mode, aperçu du prompt final. [/desc]
//
// Un seul dialogue pour les deux gestes :
//   - lancer   : premier passage (ou nouveau passage d'une tâche en échec)
//   - relancer : nouveau passage avec un RETOUR ; « continuer avec le même agent » par défaut
//                quand l'agent du dernier passage est joignable, sinon nouvel agent.
// Aucun dépôt deviné : sans `projet_defaut`, le select démarre sur « Choisir un dépôt… » et
// l'envoi est refusé AVANT l'appel réseau, champ en erreur (R4).

import { h, busy, toast, api } from "../lib/ui.js";
import { openReposDialog } from "../projects_admin.js";
import { state, marquerReprise } from "./store.js";
import * as act from "./actions.js";
import { champExecution, estOrdinaire, fichiersRefuses } from "./lancer_execution.js";

export const ENVIRONNEMENTS = [
  { value: "worktree", label: "Copie isolée", hint: "Une copie git à part (worktree) : plusieurs agents en parallèle sans se gêner. Choix par défaut." },
  { value: "shared", label: "Dépôt principal", hint: "L'agent travaille directement dans le dépôt." },
  { value: "worktree_venv", label: "Copie isolée + dépendances", hint: "Copie isolée avec son propre environnement Python (pour modifier les paquets)." },
];

// ---------------------------------------------------------------- champs

function champ(label, controle, hint) {
  const id = `bz-l-${Math.random().toString(36).slice(2, 8)}`;
  const cible = controle.matches("select, input, textarea") ? controle : (controle.querySelector("select, input, textarea") || controle);
  cible.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), controle,
    hint ? h("span", { class: "field__hint" }, hint) : null, h("span", { class: "field__error" }));
}

function erreurChamp(f, msg) {
  f.dataset.invalid = msg ? "true" : "false";
  f.querySelector(".field__error").textContent = msg || "";
}

/** Dépôts enregistrés, ceux du chantier en tête ; présélection = dépôt de la tâche (jamais deviné). */
function selectDepots(tache) {
  const sel = h("select", { class: "select", "data-role": "depot" });
  const pref = tache.projet_defaut || tache.projet_slug || "";
  const duChantier = (tache._chantier && tache._chantier.projets) || [];
  const dansChantier = (p) => (duChantier.includes(p.slug) ? 1 : 0);
  if (!pref) sel.appendChild(h("option", { value: "" }, "Choisir un dépôt…"));
  for (const p of [...state.projets].sort((a, b) => dansChantier(b) - dansChantier(a))) {
    sel.appendChild(h("option", { value: p.slug, selected: p.slug === pref },
      `${p.name || p.slug}${dansChantier(p) ? " · chantier" : ""}`));
  }
  return sel;
}

function selectProfils() {
  const sel = h("select", { class: "select", "data-role": "profil" });
  const profils = state.profils.length ? state.profils : [{ name: "default", description: "Agent standard" }];
  for (const p of profils.filter((x) => x.name !== "bureau-assistant")) {
    sel.appendChild(h("option", { value: p.name, title: p.description || null }, p.name));
  }
  sel.value = "default";
  return sel;
}

function champEnvironnement() {
  const sel = h("select", { class: "select", "data-role": "env" });
  for (const e of ENVIRONNEMENTS) sel.appendChild(h("option", { value: e.value, title: e.hint }, e.label));
  const f = champ("Environnement", sel, ENVIRONNEMENTS[0].hint);
  sel.addEventListener("change", () => {
    const e = ENVIRONNEMENTS.find((x) => x.value === sel.value);
    f.querySelector(".field__hint").textContent = e ? e.hint : "";
  });
  return { sel, f };
}

function choixDuMode(joignable) {
  const radio = (valeur, coche, desactive) => h("input", { type: "radio", name: "bz-mode", value: valeur,
    checked: coche, disabled: desactive });
  return h("fieldset", { class: "bz-launch__modes" },
    h("legend", { class: "field__label" }, "Qui reprend ?"),
    h("label", { class: "bz-radio" }, radio("continuer", joignable, !joignable),
      h("span", null, h("b", null, "Le même agent"), " — il reçoit ton retour dans sa conversation (contexte et cache conservés).",
        joignable ? null : h("em", null, " Indisponible : l'agent précédent n'est plus joignable."))),
    h("label", { class: "bz-radio" }, radio("nouvel_agent", !joignable, false),
      h("span", null, h("b", null, "Un nouvel agent"), " — il repart avec le brief, le récap des passages précédents et tes retours.")));
}

// ---------------------------------------------------------------- aperçu du prompt

function resumeApercu(r) {
  const caracteres = r.caracteres || (r.prompt || "").length;
  return `· ${caracteres} caractères · ${r.passages_inclus || 0} passage(s) · ${r.retours_inclus || 0} retour(s)`;
}

/** Aperçu repliable du prompt, recalculé à l'ouverture et 400 ms après chaque frappe dans le retour. */
function creerApercu(tache, retour) {
  const corps = h("pre", { class: "bz-launch__prompt", "aria-live": "polite" });
  const meta = h("span", { class: "field__hint" });
  const el = h("details", { class: "bz-launch__apercu" }, h("summary", null, "Aperçu du prompt envoyé à l'agent ", meta), corps);
  let seq = 0;
  let timer = null;
  async function charger() {
    const moi = ++seq;
    corps.textContent = "Calcul de l'aperçu…";
    corps.setAttribute("aria-busy", "true");
    try {
      const r = await act.apercuPrompt(tache.id, retour ? retour.value.trim() : "");
      if (moi !== seq) return;
      corps.textContent = r.prompt || "";
      meta.textContent = resumeApercu(r);
    } catch (e) {
      if (moi === seq) corps.textContent = `Aperçu indisponible : ${e.message}`;
    } finally {
      if (moi === seq) corps.removeAttribute("aria-busy");
    }
  }
  if (retour) retour.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(charger, 400); });
  return { el, charger, arreter: () => clearTimeout(timer) };
}

// ---------------------------------------------------------------- dialogue

function construire(tache, relance, o) {
  const d = { tache, relance, o, depot: selectDepots(tache), profil: selectProfils(), env: champEnvironnement() };
  d.ajoutDepot = h("button", { type: "button", class: "btn btn--sm", "data-role": "ajouter-depot" }, "+ Ajouter un dépôt…");
  d.ajoutDepot.addEventListener("click", () => openReposDialog({
    onChange: async () => {
      const res = await api("GET", "/api/projects");
      state.projets = (res && res.projects) || [];
    },
    onAdded: (slug) => {
      if (![...d.depot.options].some((op) => op.value === slug)) d.depot.appendChild(h("option", { value: slug }, slug));
      d.depot.value = slug;
      d.depot.dispatchEvent(new Event("change", { bubbles: true }));
    },
  }));
  d.fDepot = champ("Dépôt", h("div", { class: "bz-launch__depot" }, d.depot, d.ajoutDepot),
    "Obligatoire : l'agent travaillera dans ce dépôt.");
  d.retour = relance ? h("textarea", { class: "textarea", rows: "4", "data-role": "retour",
    placeholder: "Qu'est-ce qui ne va pas, qu'est-ce qui manque ?" }) : null;
  if (d.retour) d.retour.value = o.retourInitial || "";
  d.fRetour = d.retour ? champ("Ton retour", d.retour, "Ajouté à l'historique de la tâche.") : null;
  d.modes = relance ? choixDuMode(!!tache.joignable) : null;
  d.apercu = creerApercu(tache, d.retour);
  d.exec = champExecution({ projets: state.projets, principal: () => d.depot.value, indices: tache.titre });
  d.opts = h("div", { class: "bz-launch__grid", "data-role": "opts" }, d.fDepot, champ("Profil d'agent", d.profil), d.env.f);
  d.erreur = h("p", { class: "field__error bz-launch__erreur", role: "alert" });
  d.annuler = h("button", { type: "button", class: "btn" }, "Annuler");
  d.valider = h("button", { type: "submit", class: "btn btn--primary", "data-role": "go" }, relance ? "Relancer" : "Lancer l'agent");
  d.form = h("form", { class: "ui-dialog__body", method: "dialog" },
    h("h2", { class: "ui-dialog__title", id: "bz-launch-title" }, relance ? "Renvoyer avec un retour" : "Lancer un agent"),
    h("p", { class: "bz-launch__tache" }, tache.titre || ""),
    d.fRetour, d.modes, d.opts, d.exec.el, d.apercu.el, d.erreur,
    h("div", { class: "ui-dialog__actions" }, d.annuler, d.valider));
  d.dlg = h("dialog", { class: "ui-dialog bz-launch", "aria-labelledby": "bz-launch-title" }, d.form);
  return d;
}

const modeCourant = (d) => (d.modes ? (d.modes.querySelector("input[name=bz-mode]:checked") || {}).value : "nouvel_agent");

/** En mode « continuer », dépôt / profil / env sont ceux de l'agent existant : on les masque. */
function syncMode(d) {
  const cont = modeCourant(d) === "continuer";
  d.opts.hidden = cont;
  d.exec.el.hidden = cont;
  d.apercu.el.hidden = cont;
  d.valider.textContent = d.relance ? (cont ? "Envoyer le retour" : "Relancer un nouvel agent") : "Lancer l'agent";
}

/** Vérifie la saisie AVANT tout appel réseau ; renvoie false (champ en erreur, focus) si incomplète. */
function saisieValide(d) {
  d.erreur.textContent = "";
  erreurChamp(d.fDepot, "");
  const cont = modeCourant(d) === "continuer";
  if (!cont && !d.depot.value) {
    erreurChamp(d.fDepot, "Choisis le dépôt où l'agent doit travailler.");
    d.depot.focus();
    return false;
  }
  if (!cont && !d.exec.valider()) return false;
  if (d.relance && cont && !d.retour.value.trim()) {
    erreurChamp(d.fRetour, "Écris ton retour pour l'agent.");
    d.retour.focus();
    return false;
  }
  return true;
}

async function envoyer(d) {
  if (d.o.avant) await d.o.avant();
  const params = { projet_slug: d.depot.value, profil: d.profil.value, isolation: d.env.sel.value };
  // Relance : le choix est TOUJOURS envoyé (sinon le serveur reprendrait l'exécution mémorisée,
  // Rundeck compris) ; premier lancement ordinaire : rien, le prompt reste celui de l'aperçu.
  const execution = d.exec.valeur();
  if (modeCourant(d) !== "continuer" && (d.relance || !estOrdinaire(execution))) params.execution = execution;
  if (!d.relance) return act.lancerTache(d.tache.id, params);
  return act.relancerTache(d.tache.id, { ...params, retour: d.retour.value.trim(), mode: modeCourant(d) });
}

function montrerEchec(d, err) {
  const code = err.code || (err.data && err.data.code) || "";
  if (code === "depot_requis" || code === "depot_inconnu") {
    erreurChamp(d.fDepot, err.message);
    d.opts.hidden = false;
  }
  d.erreur.textContent = `${d.relance ? "Relance" : "Lancement"} impossible : ${err.message}`;
  if (code === "cible_indisponible" || code === "lancement_impossible") {
    d.erreur.textContent += " Choisis « Sur ce poste » pour lancer en local.";
  }
  if (code === "non_joignable" && d.modes) {
    d.modes.querySelector("input[value=nouvel_agent]").checked = true;
    syncMode(d);
  }
}

function messageDeSucces(d, r) {
  if (r.queued) return "L'agent travaille encore : il lira ton retour à sa prochaine étape.";
  if (d.relance && r.mode === "continuer") return "Retour envoyé à l'agent : il reprend.";
  if (r.distant) return `Lancé sur Rundeck — exécution ${r.distant.execution_id || "?"} : tu seras prévenu à la fin.`;
  return "Agent lancé — préparation de l'environnement…";
}

async function soumettre(d, fermer) {
  if (!saisieValide(d)) return;
  await busy(d.valider, d.relance ? "Envoi…" : "Lancement…", async () => {
    d.annuler.disabled = true;
    try {
      const r = await envoyer(d);
      fermer(true);
      act.toastAgent(messageDeSucces(d, r), r.agent_id || r.launch_key || "");
      if (d.relance && r.mode === "continuer") marquerReprise(d.tache.id);
      if (r.isolation_message) toast.info(r.isolation_message);
      const refuses = fichiersRefuses(r.distant);
      if (refuses.length) toast.info(`Fichiers NON transmis à la VM : ${refuses.join(", ")}`, { timeout: 15000 });
      await act.rafraichir();
    } catch (err) {
      d.annuler.disabled = false;
      montrerEchec(d, err);
    }
  });
}

function afficher(dlg) {
  if (typeof dlg.showModal !== "function") { dlg.setAttribute("open", ""); return; }
  try { dlg.showModal(); } catch (_) { dlg.setAttribute("open", ""); }
}

/**
 * Ouvre le dialogue.
 * @param {object} tache ligne de /api/lignes
 * @param {{mode:"lancer"|"relancer", avant?:()=>Promise<void>, retourInitial?:string}} o
 *   avant : enregistre le brief en attente (autosave) — à l'ouverture, pour un aperçu à jour, et avant l'envoi
 * @returns {Promise<boolean>} true si un agent est parti
 */
export function ouvrirLancement(tache, o = {}) {
  return new Promise((resolve) => {
    const precedent = document.activeElement;
    const d = construire(tache, o.mode === "relancer", o);
    document.body.appendChild(d.dlg);
    if (d.modes) d.modes.addEventListener("change", () => syncMode(d));
    d.depot.addEventListener("change", () => d.exec.charger());
    syncMode(d);
    let fini = false;
    const fermer = (ok) => {
      if (fini) return;
      fini = true;
      d.apercu.arreter();
      if (d.dlg.open) d.dlg.close();
      d.dlg.remove();
      if (precedent && precedent.isConnected && typeof precedent.focus === "function") precedent.focus();
      resolve(ok);
    };
    d.annuler.addEventListener("click", () => fermer(false));
    d.dlg.addEventListener("cancel", (e) => { e.preventDefault(); if (d.valider.getAttribute("aria-busy") !== "true") fermer(false); });
    d.form.addEventListener("submit", (e) => { e.preventDefault(); soumettre(d, fermer); });
    afficher(d.dlg);
    (d.retour || (d.depot.value ? d.valider : d.depot)).focus();
    // Le brief tapé juste avant doit être dans l'aperçu : on le fait enregistrer d'abord (l'échec éventuel
    // réapparaît à l'envoi, qui refait `avant` et le dit dans le dialogue).
    Promise.resolve(o.avant ? o.avant() : null).catch(() => {}).finally(() => d.apercu.charger());
    d.exec.charger();
  });
}
