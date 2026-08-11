// Chrome commun aux trois pages : navigation, bandeaux d'alerte, formats d'heure.
window.i18n.register("en", {
  "nav.conversations": "Conversations",
  "nav.agents": "Agents",
  "nav.api": "API",
  "nav.language": "Language",

  "banner.env_ko": "API env broken — agents cannot run.",
  "banner.env_ko_missing": "API env broken — agents cannot run. Restart via bouzeui.ps1.",
  "banner.env_unreachable": "API unreachable — network or proxy. The env is fine: recheck, don't restart.",
  "banner.env_missing_detail": "missing API environment variables: {vars} — the server was "
    + "probably restarted outside bouzeui.ps1; relaunch it via bouzeui.ps1 (rechecking will not help)",
  "banner.recheck": "Recheck",
  "banner.rechecking": "Probing…",
  "banner.version_drift": "Server drift: the booted code no longer matches the disk — restart via "
    + "bouzeui.ps1 to see your changes (running agents are unaffected).",
  "banner.drift_sha": "boot {boot} → HEAD {head}",
  "banner.drift_source": "source files changed since boot",

  // « hier 14:03 » / « 09/24 14:03 » : l'ordre jour-mois change avec la langue, il fait
  // donc partie du dictionnaire au même titre que les mots.
  "time.yesterday": "yesterday {time}",
  "time.short_date": "{month}/{day} {time}",

  // Chrome du gabarit `conversations.html`. Ce que le composer et la sidebar CONSTRUISENT
  // vit dans `conv/composer.js` et `conv/sidebar.js`.
  "conv.sidebar_title": "Conversations",
  "conv.loading": "Loading…",
  "conv.new_placeholder": "New conversation — describe what needs doing (Enter to send)…",
  "conv.send": "Send",
  "conv.options": "Options",
  "conv.agent_type": "Agent type:",
  "conv.agent_type_group": "Agent type",
  "conv.project": "Project:",
  "conv.project_group": "Project",
  "conv.environment": "Environment:",
  "conv.environment_group": "Environment",
  "conv.empty": "Pick a conversation on the left, or start a new one above.",

  // Chrome des blocs de conversation, RENDU PAR LE SERVEUR (services/message_view.py) avec
  // sa clé et son texte anglais. Commun aux pages Conversations et Session.
  "block.thinking": "💭 thinking",
  "block.context_help": "What context this turn sent to the model (cache status and the turn "
    + "each item was added on)",
  "block.tool_count_one": "{count} tool",
  "block.tool_count_many": "{count} tools",
  "block.kind_tool": "tool",
  "block.kind_subagent": "subagent",
  "block.subagent_done": "done",
  "block.verdict": "— verdict {verdict}",
  "block.subagents_launched": "🤖 {count} agents launched",
  "block.subagent_launched": "1 agent launched",
  "block.final_answer": "✅ Final answer",
  "block.closure_refused": "❌ Closure refused by the validator",
  "block.tool_result": "{name} result — {size} chars",
});
