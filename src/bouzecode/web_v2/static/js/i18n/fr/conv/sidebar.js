// Zone « sidebar » de la page Conversations : sections d'état, carte d'un agent,
// repli des sous-agents, archivage et recherche plein-texte.
// Reprend mot pour mot les libellés d'origine de l'interface.
window.i18n.register("fr", {
  "sidebar.section_needinput": "⚠ Nécessite une action",
  "sidebar.section_running": "● En cours",
  "sidebar.section_finished": "Terminés",
  "sidebar.empty": "Aucune conversation manager.",

  "sidebar.ghost_title": "⌀ conversation archivée · #{id}",
  "sidebar.ghost_tip": "Conversation parente archivée, purgée ou disparue — validateur rattaché ci-dessous.",

  "sidebar.flat_parent": "↳ sous-agent de {parent}",
  "sidebar.recap": "Récap",
  "sidebar.recap_tip": "Voir le récap structuré (symptômes, cause, tests, diffs)",
  "sidebar.branch_label": "branche",
  "sidebar.branch_tip": "branche {branch}",
  "sidebar.copy_agent_id": "Copier l'id de l'agent",
  "sidebar.copied": "copié ✓",

  "sidebar.archive": "Archiver",
  "sidebar.archive_tip": "Marquer comme traitée (archiver)",
  "sidebar.cancel_countdown": "Annuler {seconds}",

  "sidebar.subagents_one": "{n} sous-agent",
  "sidebar.subagents_many": "{n} sous-agents",
  "sidebar.children_awaiting": "{n} en attente",
  "sidebar.children_running": "{n} en cours",

  "sidebar.search_placeholder": "Rechercher un mot-clé…",
  "sidebar.search_scope_open": "Ouverts",
  "sidebar.search_scope_all": "Tous",
  "sidebar.search_error": "Erreur lors de la recherche.",
  "sidebar.search_empty": "Aucun résultat.",
  "sidebar.search_role_user": "vous",
  "sidebar.search_role_agent": "réponse",
});
