// Chrome commun aux trois pages : navigation, bandeaux d'alerte, formats d'heure.
window.i18n.register("fr", {
  "nav.conversations": "Conversations",
  "nav.agents": "Agents",
  "nav.api": "API",
  "nav.language": "Langue",

  "banner.env_ko": "ENV API KO — les agents ne peuvent pas tourner.",
  "banner.env_ko_missing": "ENV API KO — les agents ne peuvent pas tourner. Redémarrez via bouzeui.ps1.",
  "banner.env_unreachable": "API injoignable — réseau/proxy. L'env est bonne : revérifiez, ne redémarrez pas.",
  "banner.env_missing_detail": "variables d'environnement API absentes: {vars} — le serveur a "
    + "probablement été relancé hors bouzeui.ps1 ; relance-le via bouzeui.ps1 "
    + "(revérifier ne suffira pas)",
  "banner.recheck": "Revérifier",
  "banner.rechecking": "Re-sonde…",
  "banner.version_drift": "Serveur en dérive : le code du boot n'est plus celui du disque — redémarrez "
    + "via bouzeui.ps1 pour voir les changements (les agents en cours ne sont pas bloqués).",
  "banner.drift_sha": "boot {boot} → HEAD {head}",
  "banner.drift_source": "fichiers source modifiés depuis le boot",

  "time.yesterday": "hier {time}",
  "time.short_date": "{day}/{month} {time}",

  "conv.sidebar_title": "Conversations",
  "conv.loading": "Chargement…",
  "conv.new_placeholder": "Nouvelle conversation — décris ce qu'il faut faire (Entrée pour envoyer)…",
  "conv.send": "Envoyer",
  "conv.options": "Options",
  "conv.agent_type": "Type d'agent :",
  "conv.agent_type_group": "Type d'agent",
  "conv.project": "Projet :",
  "conv.project_group": "Projet",
  "conv.environment": "Environnement :",
  "conv.environment_group": "Environnement",
  "conv.empty": "Sélectionne une conversation à gauche, ou lance-en une nouvelle ci-dessus.",

  "block.thinking": "💭 réflexion",
  "block.context_help": "Détail du contexte envoyé au modèle à ce tour "
    + "(statut cache + tour d'ajout par élément)",
  "block.tool_count_one": "{count} outil",
  "block.tool_count_many": "{count} outils",
  "block.kind_tool": "outil",
  "block.kind_subagent": "sous-agent",
  "block.subagent_done": "terminé",
  "block.verdict": "— verdict {verdict}",
  "block.subagents_launched": "🤖 {count} agents lancés",
  "block.subagent_launched": "1 agent lancé",
  "block.final_answer": "✅ Réponse finale",
  "block.closure_refused": "❌ Clôture refusée par le validateur",
  "block.tool_result": "résultat {name} — {size} car.",
});
