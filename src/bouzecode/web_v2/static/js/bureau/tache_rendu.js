// [desc] Task submission form that serializes FinalAnswer fields, commits and test details to the API, and reloads them for review. [/desc]
//
// Mêmes champs que l'outil FinalAnswer : answer (sections ## 1. … ## 6.), recap
// {symptoms, explanation, tests, changes[{file, summary}]}, taches_terminees, taches_restantes,
// plus ce qu'un humain doit prouver autrement : les commits (vérifiés avec git côté serveur) et
// le détail des tests. Le serveur applique close_validator : un champ manquant revient en 400
// `rendu_incomplet` avec la liste `manquants`, affichée ici telle quelle.

import { h, api, toast } from "../lib/ui.js";
import { fichiersLivres } from "../lib/fichiers_livres.js";

const MODELE_ANSWER = [
  "## 1. Résumé", "", "## 2. Cause / besoin", "", "## 3. Solution", "",
  "## 4. Tests", "", "## 5. Fichiers modifiés", "", "## 6. Reste à faire", "",
].join("\n");

const lignes = (txt) => String(txt || "").split("\n").map((l) => l.trim()).filter(Boolean);
const colonnes = (ligne) => ligne.split("|").map((c) => c.trim());

/** Texte des zones « une ligne par élément » → objets attendus par l'API. */
export function lireFormulaire(champs) {
  const v = (nom) => champs[nom].type === "checkbox" ? champs[nom].checked : champs[nom].value;
  const nombre = parseInt(v("tests_nombre"), 10);
  return {
    auteur: v("auteur").trim(),
    answer: v("answer"),
    recap: {
      symptoms: v("symptoms").trim(),
      explanation: v("explanation").trim(),
      tests: v("tests").trim(),
      changes: lignes(v("changes")).map((l) => { const [file, ...r] = colonnes(l); return { file, summary: r.join(" | ") }; }),
    },
    tests_detail: {
      nombre: Number.isFinite(nombre) ? nombre : null,
      niveau: v("tests_niveau").trim(),
      verts: v("tests_verts"),
      chemin: v("tests_chemin").trim(),
    },
    commits: lignes(v("commits")).map((l) => { const [sha, branche] = l.split(/\s+/); return { sha, branche: branche || "" }; }),
    taches_terminees: lignes(v("taches_terminees")),
    taches_restantes: lignes(v("taches_restantes")).map((l) => {
      const [titre, corps, drapeau] = colonnes(l);
      return { titre, corps: corps || "", decision: /^d[ée]cision$/i.test(drapeau || "") };
    }),
    related_files: lignes(v("related_files")).map((l) => {
      const [path, label, kind] = colonnes(l);
      const f = { path };
      if (label) f.label = label;
      if (kind) f.kind = kind;
      return f;
    }),
  };
}

/** Rendu enregistré → valeurs des champs (relecture). */
export function remplirFormulaire(champs, r) {
  if (!r) return;
  const recap = r.recap || {}, td = r.tests_detail || {};
  const poser = (nom, val) => { if (champs[nom].type === "checkbox") champs[nom].checked = !!val; else champs[nom].value = val ?? ""; };
  poser("auteur", r.auteur);
  poser("answer", r.answer);
  poser("symptoms", recap.symptoms);
  poser("explanation", recap.explanation);
  poser("tests", recap.tests);
  poser("changes", (recap.changes || []).map((c) => `${c.file} | ${c.summary}`).join("\n"));
  poser("tests_nombre", td.nombre ?? "");
  poser("tests_niveau", td.niveau);
  poser("tests_verts", td.verts);
  poser("tests_chemin", td.chemin);
  poser("commits", (r.commits || []).map((c) => `${c.sha} ${c.branche || ""}`.trim()).join("\n"));
  poser("taches_terminees", (r.taches_terminees || []).join("\n"));
  poser("taches_restantes", (r.taches_restantes || []).map((t) =>
    [t.titre, t.corps || "", t.decision ? "decision" : ""].join(" | ").replace(/( \| )+$/, "")).join("\n"));
  poser("related_files", (r.related_files || []).map((f) =>
    [f.path, f.label || "", f.kind || ""].join(" | ").replace(/( \| )+$/, "")).join("\n"));
}

function champ(champs, nom, libelle, el, aide) {
  el.setAttribute("name", nom);
  el.setAttribute("data-rendu", nom);
  champs[nom] = el;
  return h("div", { class: "field" }, h("label", null, libelle), el, aide ? h("div", { class: "muted small" }, aide) : null);
}
const zone = (rows, placeholder = "") => { const t = h("textarea", { rows: String(rows) }); t.placeholder = placeholder; return t; };
const saisie = (type = "text", placeholder = "") => { const i = h("input", { type }); i.placeholder = placeholder; return i; };

/** Formulaire de rendu d'une tâche ; `microId` = id de la micro. Charge le dernier rendu. */
export function formulaireRendu(microId) {
  const champs = {};
  const statut = h("div", { class: "bz-rendu__statut", "data-rendu": "statut" });
  const erreurs = h("div", { class: "bz-rendu__erreurs", "data-rendu": "erreurs" });
  const fichiersZone = h("div", { class: "bz-rendu__fichiers", "data-rendu": "fichiers" });
  const answer = zone(12);
  answer.value = MODELE_ANSWER;
  const form = h("form", { class: "bz-rendu" },
    champ(champs, "auteur", "Auteur", saisie("text", "ton nom")),
    champ(champs, "symptoms", "Symptômes / besoin", zone(3)),
    champ(champs, "explanation", "Explication (cause ou plan)", zone(3)),
    champ(champs, "tests", "Tests (résumé)", zone(2), "Vide : composé depuis le détail ci-dessous."),
    champ(champs, "tests_nombre", "Nombre de tests", saisie("number")),
    champ(champs, "tests_niveau", "Niveau", saisie("text", "unitaire, route, e2e…")),
    champ(champs, "tests_verts", "Tests verts", saisie("checkbox")),
    champ(champs, "tests_chemin", "Lien ou chemin des tests", saisie("text")),
    champ(champs, "commits", "Commit(s)", zone(2, "sha branche"), "Un par ligne : « sha branche » — vérifiés avec git."),
    champ(champs, "changes", "Fichiers modifiés", zone(3, "chemin/fichier.py | ce qu'il apporte"), "Un par ligne : « fichier | résumé »."),
    champ(champs, "taches_terminees", "Tâches terminées", zone(3), "Une par ligne."),
    champ(champs, "taches_restantes", "Tâches restantes", zone(3, "titre | brief | decision"),
      "Une par ligne : « titre | brief » ; ajoute « | decision » si un humain doit trancher. Vide = rien ne reste."),
    champ(champs, "related_files", "Fichiers livrés", zone(3, "C:\\chemin\\absolu\\rapport.html | libellé | kind"),
      "Un par ligne : « chemin absolu | libellé | type » — livrables à consulter (.html, .pptx, .pbix, .xlsx, .pdf…)."),
    champ(champs, "answer", "Rapport (6 sections ## 1. … ## 6.)", answer),
    erreurs,
    h("div", { class: "btn-row" }, h("button", { type: "submit", class: "btn btn--primary", "data-rendu": "envoyer" }, "Rendre la tâche")),
    statut, fichiersZone);
  const montrerFichiers = (files) => {
    const s = fichiersLivres(files, { micro_id: microId });
    fichiersZone.replaceChildren(...(s ? [s] : []));
  };
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    erreurs.textContent = "";
    try {
      const res = await api("POST", `/api/micros/${encodeURIComponent(microId)}/rendu`, lireFormulaire(champs));
      statut.textContent = `Rendu enregistré (ticket ${res.ticket_id}) : la tâche passe « À vérifier ».`;
      api("GET", `/api/micros/${encodeURIComponent(microId)}/rendu`)
        .then((r) => montrerFichiers(r && r.rendu && r.rendu.related_files)).catch(() => {});
      toast("Tâche rendue", "ok");
    } catch (e) {
      const manquants = e?.data?.error?.details?.manquants || [];
      erreurs.textContent = (e?.message || "Rendu refusé") + (manquants.length ? ` — manquants : ${manquants.join(", ")}` : "");
    }
  });
  api("GET", `/api/micros/${encodeURIComponent(microId)}/rendu`).then((res) => {
    if (res && res.rendu) {
      remplirFormulaire(champs, res.rendu);
      montrerFichiers(res.rendu.related_files);
      statut.textContent = `Dernier rendu : ticket ${res.rendu.ticket_id || "?"}${res.rendu.at ? ` (${res.rendu.at})` : ""}.`;
    }
  }).catch(() => {});
  return form;
}

/** Onglet repliable « Rendu » ; le formulaire n'est monté qu'à la 1re ouverture (et jamais réécrit par le poll). */
export function zoneRendu(rec) {
  const det = h("details", { class: "bz-rendu-onglet", "data-rendu": "onglet" }, h("summary", null, "Rendu"));
  det.addEventListener("toggle", () => {
    if (det.open && !det.dataset.monte) {
      det.dataset.monte = "1";
      det.appendChild(formulaireRendu(String(rec.id)));
    }
  });
  return det;
}
