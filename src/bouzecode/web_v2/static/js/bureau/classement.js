// [desc] Ce qu'une tâche classée dit d'elle-même : « Faite par « X » — commentaire (commentaire de l'assistant, 25/09 03:12) », « Doublon de « Y » », « Caduque » — et l'historique de ses classements rouverts. Pur : aucun appel, aucun DOM. [/desc]
//
// Le serveur envoie `classement` {motif, libelle, commentaire, auteur, at, lien:{id,titre}|null}
// (sinon null) et `classements` (historique, rouverts compris : + rouvert_at, rouvert_par).
// La même phrase est composée côté serveur pour l'assistant (services/work/classement.py::texte).

import { parseInstant } from "../time_format.js";

const pad = (n) => String(n).padStart(2, "0");

/** « 25/09 03:12 » (heure locale) ; "" si la date est illisible. */
export function dateCourte(iso) {
  const d = parseInstant(iso);
  if (!d) return "";
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const cible = (lien) => (lien ? `« ${lien.titre || lien.id} »` : "");

/** Le début de la phrase : ce qu'est devenue la tâche, et vers quoi elle renvoie. */
export function teteClassement(c) {
  if (c.motif === "doublon") return `Doublon de ${cible(c.lien)}`.trim();
  if (c.motif === "faite") return c.lien ? `Faite par ${cible(c.lien)}` : "Faite";
  return c.libelle || "Caduque";
}

const QUI = { assistant: "l'assistant", agent: "un agent", humain: "toi" };
const DE_QUI = { assistant: "de l'assistant", agent: "d'un agent" };

/** Qui l'a dit et quand : « commentaire de l'assistant, 25/09 03:12 » / « marquée par toi, … ».
 *  Auteur « agent » : un agent non-bureau (outil TachesProjet) ; son commentaire porte
 *  la signature « [agent … · ticket …] ». */
export function signature(c) {
  const qui = QUI[c.auteur] || QUI.humain;
  const quoi = c.commentaire ? (DE_QUI[c.auteur] ? `commentaire ${DE_QUI[c.auteur]}` : "ton commentaire")
    : `marquée par ${qui}`;
  const quand = dateCourte(c.at);
  return quand ? `${quoi}, ${quand}` : quoi;
}

/** La ligne secondaire d'une tâche classée ; "" si elle n'a pas de classement motivé. */
export function texteClassement(c) {
  if (!c) return "";
  const corps = c.commentaire ? ` — ${c.commentaire}` : "";
  return `${teteClassement(c)}${corps} (${signature(c)})`;
}

/** Une entrée de l'historique : la phrase, puis « rouverte le … par … » si elle l'a été. */
export function texteHistorique(c) {
  if (!c.rouvert_at) return texteClassement(c);
  const par = QUI[c.rouvert_par] || QUI.humain;
  return `${texteClassement(c)} — rouverte ${dateCourte(c.rouvert_at)} par ${par}`;
}
