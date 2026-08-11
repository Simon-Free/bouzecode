// Vocabulaire d'ÉTAT : pastilles, phases de lancement, activité d'un agent vivant.
// Partagé par la sidebar, les chips de sous-agents et la ligne meta d'un onglet — c'est
// ce qui garantit qu'un agent ne peut pas être « Done » ici et « Crashed » ailleurs.
window.i18n.register("en", {
  "state.running": "running",
  "state.starting": "starting…",
  "state.provisioning": "preparing…",
  "state.awaiting_input": "needs reply",
  "state.awaiting_plan_validation": "plan to approve",
  "state.idle": "warm",
  "state.finished": "done",
  "state.crashed": "crashed",
  "state.waiting_children": "⏳ orchestrating",
  "state.cli": "cli",
  "state.ko": "KO",
  "state.archived": "archived",
  "state.needs_reply": "needs attention",
  "state.dead_maybe": "dead?",
  "state.tip_crashed": "Agent died with no proven closure (no FinalAnswer, no verdict): relaunch it.",
  "state.tip_dead_maybe": "Agent suspected dead: finished without a single turn and exited non-zero.",

  // Phases servies par le serveur sous forme de CLÉ (`status.phase` / `node.phase`) : le
  // client choisit les mots, le serveur reste monolingue.
  "phase.demarrage": "starting the agent…",
  "phase.demarrage_detail": "A fresh process is booting: loading the harness and reading the project.",
  "phase.attente_modele": "the model is reading your request…",
  "phase.attente_modele_detail": "The first answer takes longer: the model is putting your context in "
    + "memory. The next ones will be markedly faster.",
  "phase.provisioning_worktree": "creating the worktree",
  "phase.syncing_venv": "installing the uv environment",
  "phase.spawning": "starting the agent",
  "phase.reisolating": "re-isolating the worktree",
  "phase.venv_ready": "uv environment ready",
  "phase.venv_failed": "uv environment failed",
  "phase.launching_fallback": "preparing…",

  // Activité recomposée côté client à partir de `activity` + `activity_live` + `idle_seconds`.
  "activity.starting": "process starting",
  "activity.idle": "warm and idle, reachable",
  "activity.awaiting_input": "waiting for your reply",
  "activity.awaiting_plan_validation": "waiting for plan approval",
  "activity.tool_live": "{tool} running",
  "activity.tool_live_since": "{tool} running for {age}",
  "activity.tool_last": "last tool seen: {tool}",
  "activity.tool_last_since": "last tool seen: {tool}, {age} ago",
  "activity.llm": "calling the model",
  "activity.llm_since": "calling the model for {age}",
  "activity.stale_tip": "No heartbeat for over 4 minutes: the agent may be holding a long tool, or it "
    + "may be stuck. Worth a look — this is not a death certificate.",

  "age.seconds": "{n} s",
  "age.minutes": "{n} min",
  "age.hours": "{h} h {m}",
});
