// [desc] Ce que l'utilisateur doit FAIRE (SPEC §4.2) : les quatre catégories d'attention (décider, débloquer à la main, reprendre, vérifier) et, par motif servi par le serveur, le mot de la ligne, l'explication et le ton. [/desc]
//
// Le serveur classe (services/work/lexique.py::motif_attente) : chaque tâche ou point hors tâche
// qui attend un geste porte un `motif`. Ici, seulement ce que l'écran en dit.

import { badge, LEXIQUE } from "../lib/states.js";

/** Groupes de « À traiter », dans l'ordre d'urgence. */
export const CATEGORIES = [
  { key: "decider", titre: "Décider",
    aide: "Un agent attend ta réponse, la validation de son plan, ou t'a laissé un choix à faire." },
  { key: "debloquer", titre: "Action manuelle requise",
    aide: "L'agent n'a pas pu démarrer : corrige le dépôt ou l'environnement, puis relance." },
  { key: "reprendre", titre: "Reprendre un agent arrêté",
    aide: "L'agent s'est arrêté avant sa réponse finale : fais-le continuer ou relance un agent neuf." },
  { key: "verifier", titre: "Vérifier et clore",
    aide: "L'agent a rendu sa réponse finale : vérifie son travail, puis clos la tâche ou renvoie-la avec un retour." },
];

/** Par motif : catégorie, mot court de la ligne, ton, icône, explication (infobulle). Le mot, le ton,
 *  l'icône et l'aide sont ceux du lexique unique du serveur (motif → entrée : `LEXIQUE.motifs`) —
 *  le badge d'une tâche qui t'attend dit le MÊME mot que l'état de son agent sur la page Agents.
 *  Les valeurs écrites ici n'en sont que la copie par défaut (tests/test_lexique_unique.py). */
export const MOTIFS = {
  question: { cat: "decider", mot: "Attend ta réponse", tone: "warn", icon: "?",
    aide: "L'agent t'a posé une question et attend ta réponse pour continuer." },
  plan: { cat: "decider", mot: "Plan à valider", tone: "warn", icon: "?",
    aide: "L'agent attend que tu valides son plan avant de continuer." },
  point: { cat: "decider", mot: "À décider", tone: "warn", icon: "◆",
    aide: "Un agent a fini en te laissant ce choix. Aucun agent n'attend : note ta décision, ou confie-la à un agent." },
  lancement: { cat: "debloquer", mot: "Lancement échoué", tone: "danger", icon: "!",
    aide: "L'agent n'a jamais démarré (dépôt, git, environnement, API) : corrige la cause, puis relance." },
  plante: { cat: "reprendre", mot: "Arrêté sans finir", tone: "danger", icon: "!",
    aide: "L'agent s'est arrêté sans rendre de réponse finale : fais-le continuer, ou relance un agent neuf." },
  arrete: { cat: "reprendre", mot: "Arrêté par toi", tone: "neutral", icon: "■",
    aide: "Tu as arrêté l'agent : fais-le continuer, relance, ou abandonne la tâche." },
  introuvable: { cat: "reprendre", mot: "Agent introuvable", tone: "danger", icon: "!",
    aide: "La fiche de l'agent est introuvable : relance un agent neuf." },
  livraison: { cat: "verifier", mot: "À vérifier", tone: "ok", icon: "✓",
    aide: "L'agent a rendu sa réponse finale : vérifie son travail, puis clos la tâche ou renvoie-la avec un retour." },
};

for (const [motif, info] of Object.entries(MOTIFS)) {
  const cle = LEXIQUE && LEXIQUE.motifs && LEXIQUE.motifs[motif];
  const e = cle && LEXIQUE.entrees[cle];
  if (e) Object.assign(info, { mot: e.mot || info.mot, aide: e.aide || info.aide, tone: e.ton || info.tone, icon: e.icone || info.icon });
}

/** Motif par défaut d'un statut qui t'attend, quand le serveur n'en dit pas plus. */
const MOTIF_DU_STATUT = { a_repondre: "question", a_decider: "point", en_echec: "plante", a_relire: "livraison" };

/** Motif d'une tâche : le sien (servi par /api/lignes, qui fait foi), sinon celui de son point
 *  d'attente, sinon celui de son statut ; "" si rien n'attend (ou si l'agent vient d'être relancé). */
export function motifDe(t, point) {
  if (!t || t._reprise) return "";
  const m = "motif" in t ? t.motif : ((point && point.motif) || MOTIF_DU_STATUT[t.statut_ui] || "");
  return MOTIFS[m] ? m : "";
}

/** Catégorie (clé de CATEGORIES) d'un motif ; "" si inconnu. */
export const categorieDe = (motif) => (MOTIFS[motif] ? MOTIFS[motif].cat : "");

/** Badge léger d'un motif : icône + mot court, explication en infobulle. */
export function badgeMotif(motif) {
  const m = MOTIFS[motif];
  return badge({ key: motif, label: m.mot, tone: m.tone, icon: m.icon }, { title: m.aide });
}
