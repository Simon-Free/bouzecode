// Ce qu'un agent FAIT en ce moment, écrit dans la langue de l'utilisateur.
//
// Le serveur compose déjà cette phrase (`activity.describe` → `activity_label`) et continue
// de la servir telle quelle à l'API et aux agents de monitoring : il ne négocie pas de
// langue. L'interface, elle, est bilingue — elle recompose donc la phrase à partir des FAITS
// structurés servis à côté du libellé : `activity` (le mot de code : un état, un ou plusieurs
// outils, ou « llm »), `activity_live` (le process l'exécute MAINTENANT, ou bien c'est le
// dernier outil qu'on a vu passer) et `idle_seconds`. Aucun canal nouveau, aucune requête de
// plus : ces champs étaient déjà là, seul `activity_live` a dû être ajouté.

import { t, has } from "../i18n/index.js";

// Même découpage que `activity.human_age` côté serveur, pour que les deux surfaces ne
// donnent jamais deux âges différents du même silence.
export function humanAge(seconds) {
  if (typeof seconds !== "number" || seconds < 0) return "";
  if (seconds < 60) return t("age.seconds", { n: Math.floor(seconds) });
  if (seconds < 3600) return t("age.minutes", { n: Math.floor(seconds / 60) });
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return t("age.hours", { h: hours, m: String(minutes).padStart(2, "0") });
}

// Une attente ou un démarrage se DÉCRIT par son état, pas par un outil (même règle que
// `_LABELS_BY_STATE` côté serveur) : nommer le dernier outil d'un agent qui attend une
// réponse ferait croire qu'il travaille.
const STATE_ACTIVITIES = new Set([
  "starting", "idle", "awaiting_input", "awaiting_plan_validation",
]);

export function activityLabel(node) {
  const activity = node.activity || "";
  if (!activity) return "";
  if (STATE_ACTIVITIES.has(activity)) return t("activity." + activity);
  // Node servi par un cache antérieur à `activity_live` : la distinction « en cours » /
  // « dernier outil vu » est indécidable ici, on rend donc la phrase du serveur plutôt que
  // d'affirmer la mauvaise des deux.
  if (node.activity_live === undefined) return node.activity_label || "";
  const age = humanAge(node.idle_seconds);
  if (activity === "llm") return age ? t("activity.llm_since", { age }) : t("activity.llm");
  const kind = node.activity_live ? "tool_live" : "tool_last";
  return age
    ? t("activity." + kind + "_since", { tool: activity, age })
    : t("activity." + kind, { tool: activity });
}

// Phase de lancement d'un ticket. Le serveur sert la CLÉ (`phase`) à côté de son libellé
// français (`phase_label`) : on traduit la clé quand on la connaît, sinon on rend le libellé
// du serveur — une phase inconnue du dictionnaire est une donnée, pas un libellé oublié.
export function phaseLabel(node) {
  const phase = node.phase || "";
  if (!phase) return "";
  const key = "phase." + phase;
  return has(key) ? t(key) : (node.phase_label || phase);
}

// Texte de la chip d'activité d'une carte : ce que l'agent fait, ou l'étape du lancement en
// cours. `phase_detail` (base du worktree, « essai 2/3 échoué… ») reste du texte libre
// composé par le serveur : il porte des données, pas un libellé, et n'est pas traduit.
export function activityChipText(node) {
  const phrase = activityLabel(node) || phaseLabel(node);
  if (!phrase) return "";
  return node.phase_detail ? `${phrase} — ${node.phase_detail}` : phrase;
}
