// Zone « panel » de la page Conversations : ligne meta, corps d'un onglet, bloc
// question, composer, rail des sous-agents, vue Récap et bouton de relance.
window.i18n.register("en", {
  // Ligne meta + menu « document » (chemin du session.json).
  "panel.path_unavailable": "(path unavailable)",
  "panel.copy": "Copy",
  "panel.copied": "Copied ✓",
  "panel.copy_failed": "Copy failed",
  "panel.download": "Download",
  "panel.copy_id_tip": "Copy the full id",
  "panel.copied_short": "copied ✓",
  "panel.session_doc_tip": "Session path — Copy / Download",
  "panel.session_doc_aria": "Session details",

  // Corps d'un onglet encore vide. La PHASE (cf. `phase.*` dans state.js) prime ;
  // ces libellés ne servent que lorsque le serveur n'en sert aucune.
  "panel.waiting_starting": "Starting the agent…",
  "panel.waiting_content": "Waiting for content…",
  "panel.waiting_empty": "No content (session empty or not found).",
  "panel.preparing_conversation": "Preparing the conversation…",

  // Bloc question / reprise d'un agent interrompu.
  "panel.interrupted_question": "This agent was interrupted (crash or restart). "
    + "Resume where it left off?",
  "panel.resume": "Resume",
  "panel.resume_failed": "Resume failed: {detail}",

  // Envoi d'un message (POST /continue) et ses échecs.
  "panel.interrupting": "interrupting…",
  "panel.interrupt_failed": "the agent could not be interrupted, try again.",
  "panel.send_blocked": "cannot send — interrupt the agent first (Ctrl+C).",
  "panel.network_retry": "network error: try again.",

  // Streaming token-par-token du tour en cours.
  "panel.thinking_live": "Thinking…",
  "panel.thinking": "Thinking",
  "panel.tool_running": "Tool running: {tool}",

  // Onglet : segmented control, composer, onglet ouvert par une relance.
  "panel.view_conversation": "Conversation",
  "panel.view_recap": "Recap",
  "panel.recap_disabled_tip": "available once the session ends",
  "panel.input_placeholder": "Message / follow-up… (Enter to send, Ctrl+C to interrupt)",
  "panel.send": "Send",
  "panel.relaunch_tab": "Relaunch",

  // Vue Récap.
  "panel.recap_enabled_tip": "View the structured recap",
  "panel.recap_cta": "View recap →",
  "panel.recap_loading": "Loading the recap…",
  "panel.recap_load_error": "Failed to load the recap.",
  "panel.recap_missing": "No recap generated (session without a structured recap).",
  "panel.recap_no_children": "No subagent recap for this batch.",
  "panel.recap_agg_intro": "{count} subagent(s) — consolidated recap for the batch:",
  "panel.recap_open_child": "Open this subagent's conversation",
  "panel.recap_child_missing": "Recap unavailable — see the subagent's conversation.",
  "panel.recap_symptoms": "Symptoms",
  "panel.recap_explanation": "Cause / plan",
  "panel.recap_section_changes": "Changes",
  "panel.recap_section_other": "Other changes",
  "panel.recap_section_tests": "Tests",
  "panel.recap_section_all": "Diffs",
  "panel.diff_truncated": "… ({n} more lines hidden)",

  // Bouton de relance d'un ticket dont l'agent est mort.
  "panel.relaunch": "Relaunch",
  "panel.relaunch_tip": "Create a new agent on this ticket (re-provisions the worktree)",
  "panel.relaunch_confirm": "Relaunch this ticket?\n\nA NEW agent is created and the worktree "
    + "is re-provisioned (can take ~45 s). The dead agent is not resumed: its uncommitted "
    + "work stays in the worktree.",
  "panel.relaunching": "Relaunching…",
  "panel.relaunched": "Relaunched ✓",
  "panel.relaunch_failed_network": "Relaunch failed: {detail}",
  "panel.relaunch_failed_http": "Relaunch failed (HTTP {status})",
  "panel.relaunch_failed_http_detail": "Relaunch failed (HTTP {status}): {detail}",
});
