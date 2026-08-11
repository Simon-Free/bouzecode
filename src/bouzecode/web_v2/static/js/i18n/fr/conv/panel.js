// Zone « panel » de la page Conversations : ligne meta, corps d'un onglet, bloc
// question, composer, rail des sous-agents, vue Récap et bouton de relance.
// Reprend mot pour mot les libellés d'origine de l'interface.
window.i18n.register("fr", {
  // Ligne meta + menu « document » (chemin du session.json).
  "panel.path_unavailable": "(chemin indisponible)",
  "panel.copy": "Copier",
  "panel.copied": "Copié ✓",
  "panel.copy_failed": "Échec copie",
  "panel.download": "Télécharger",
  "panel.copy_id_tip": "Copier l'id complet",
  "panel.copied_short": "copié ✓",
  "panel.session_doc_tip": "Chemin de session — Copier / Télécharger",
  "panel.session_doc_aria": "Détails de la session",

  // Corps d'un onglet encore vide. La PHASE (cf. `phase.*` dans state.js) prime ;
  // ces libellés ne servent que lorsque le serveur n'en sert aucune.
  "panel.waiting_starting": "Démarrage de l'agent…",
  "panel.waiting_content": "En attente de contenu…",
  "panel.waiting_empty": "Aucun contenu (session vide ou introuvable).",
  "panel.preparing_conversation": "Préparation de la conversation…",

  // Bloc question / reprise d'un agent interrompu.
  "panel.interrupted_question": "Cet agent a été interrompu (crash ou redémarrage). "
    + "Reprendre là où il en était ?",
  "panel.resume": "Reprendre",
  "panel.resume_failed": "La reprise a échoué : {detail}",

  // Envoi d'un message (POST /continue) et ses échecs.
  "panel.interrupting": "interruption en cours…",
  "panel.interrupt_failed": "l'agent n'a pas pu être interrompu, réessaie.",
  "panel.send_blocked": "envoi impossible — interromps l'agent d'abord (Ctrl+C).",
  "panel.network_retry": "réseau : réessaie.",

  // Streaming token-par-token du tour en cours.
  "panel.thinking_live": "Réflexion en cours…",
  "panel.thinking": "Réflexion",
  "panel.tool_running": "Outil en cours : {tool}",

  // Onglet : segmented control, composer, onglet ouvert par une relance.
  "panel.view_conversation": "Conversation",
  "panel.view_recap": "Recap",
  "panel.recap_disabled_tip": "disponible a la fin de la session",
  "panel.input_placeholder": "Message / précision… (Entrée pour envoyer, Ctrl+C pour interrompre)",
  "panel.send": "Envoyer",
  "panel.relaunch_tab": "Relance",

  // Vue Récap.
  "panel.recap_enabled_tip": "Voir le récap structuré",
  "panel.recap_cta": "Voir le recap →",
  "panel.recap_loading": "Chargement du récap…",
  "panel.recap_load_error": "Erreur au chargement du récap.",
  "panel.recap_missing": "Récap non généré (session sans récap structuré).",
  "panel.recap_no_children": "Aucun récap de sous-agent pour ce lot.",
  "panel.recap_agg_intro": "{count} sous-agent(s) — récap consolidé du lot :",
  "panel.recap_open_child": "Ouvrir la conversation de ce sous-agent",
  "panel.recap_child_missing": "Récap non disponible — voir la conversation du sous-agent.",
  "panel.recap_symptoms": "Symptômes",
  "panel.recap_explanation": "Cause / plan",
  "panel.recap_section_changes": "Modifications",
  "panel.recap_section_other": "Autres modifications",
  "panel.recap_section_tests": "Tests",
  "panel.recap_section_all": "Diffs",
  "panel.diff_truncated": "… ({n} lignes supplémentaires masquées)",

  // Bouton de relance d'un ticket dont l'agent est mort.
  "panel.relaunch": "Relancer",
  "panel.relaunch_tip": "Créer un nouvel agent sur ce ticket (re-provisionne le worktree)",
  "panel.relaunch_confirm": "Relancer ce ticket ?\n\nUn NOUVEL agent est créé et le worktree "
    + "est re-provisionné (peut prendre ~45 s). L'agent mort n'est pas repris : son travail "
    + "non commité reste dans le worktree.",
  "panel.relaunching": "Relance en cours…",
  "panel.relaunched": "Relancé ✓",
  "panel.relaunch_failed_network": "Relance impossible : {detail}",
  "panel.relaunch_failed_http": "Relance impossible (HTTP {status})",
  "panel.relaunch_failed_http_detail": "Relance impossible (HTTP {status}) : {detail}",
});
