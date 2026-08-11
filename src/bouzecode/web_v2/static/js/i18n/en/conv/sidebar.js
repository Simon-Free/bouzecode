// Zone « sidebar » de la page Conversations : sections d'état, carte d'un agent,
// repli des sous-agents, archivage et recherche plein-texte.
window.i18n.register("en", {
  // Sections d'état de #conv-list (ordre fixe a→b→c).
  "sidebar.section_needinput": "⚠ Needs attention",
  "sidebar.section_running": "● Running",
  "sidebar.section_finished": "Done",
  "sidebar.empty": "No manager conversation.",

  // Entrée fantôme : parent archivé/purgé synthétisé pour porter ses orphelins.
  "sidebar.ghost_title": "⌀ archived conversation · #{id}",
  "sidebar.ghost_tip": "Parent conversation archived, purged or gone — validator attached below.",

  // Carte d'un agent.
  "sidebar.flat_parent": "↳ subagent of {parent}",
  "sidebar.recap": "Recap",
  "sidebar.recap_tip": "View the structured recap (symptoms, cause, tests, diffs)",
  "sidebar.branch_label": "branch",
  "sidebar.branch_tip": "branch {branch}",
  "sidebar.copy_agent_id": "Copy the agent id",
  "sidebar.copied": "copied ✓",

  // Archivage : décompte annulable de 3 s avant l'appel réel.
  "sidebar.archive": "Archive",
  "sidebar.archive_tip": "Mark as handled (archive)",
  "sidebar.cancel_countdown": "Cancel {seconds}",

  // En-tête de repli d'une carte : « 2 subagents · 1 waiting · 1 running ».
  "sidebar.subagents_one": "{n} subagent",
  "sidebar.subagents_many": "{n} subagents",
  "sidebar.children_awaiting": "{n} waiting",
  "sidebar.children_running": "{n} running",

  // Recherche plein-texte au-dessus de la liste.
  "sidebar.search_placeholder": "Search a keyword…",
  "sidebar.search_scope_open": "Open",
  "sidebar.search_scope_all": "All",
  "sidebar.search_error": "Search failed.",
  "sidebar.search_empty": "No results.",
  "sidebar.search_role_user": "you",
  "sidebar.search_role_agent": "reply",
});
