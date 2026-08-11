# [desc] English/French wording printed by the /agent, /agent install and /agent-upgrade commands. [/desc]
"""Messages printed by the `/agent*` slash commands, as (english, french).

Colours and glyphs (← →) stay at the call site, as in `terminal.py`. Command names
and their placeholders are part of the message: `/agent <name>` reads as `/agent
<nom>` in French, and a user who copies the line must get something that runs.

The French of `/agent-upgrade` used to be written without accents (`Mise a jour`,
`ECHEC`); it is spelled properly here — same wording, correct accents.
"""
from __future__ import annotations

AGENT_MESSAGES: dict[str, tuple[str, str]] = {
    # --- /agent listing -------------------------------------------------------
    "agent.section_heading": ("\n  {title}:", "\n  {title} :"),
    "agent.active_marker": ("active", "actif"),
    "agent.install_hint": ("   → install: ", "   → installer : "),
    "agent.install_usage_arg": ("/agent install <name>", "/agent install <nom>"),
    "agent.active_label": ("  Active agent: ", "  Agent actif : "),
    "agent.no_active": ("(none — default agent)", "(aucun — agent par défaut)"),
    "agent.section_system": ("System agents", "Agents système"),
    "agent.section_installed": ("Installed agents", "Agents installés"),
    "agent.section_available": (
        "Available agents (shared catalog)",
        "Agents disponibles (catalogue partagé)",
    ),
    "agent.switch_label": ("\n  Switch: ", "\n  Basculer : "),
    "agent.switch_usage": (
        "/agent <name>   |   back: /agent default",
        "/agent <nom>   |   revenir : /agent default",
    ),
    "agent.build_label": ("  Build or edit an agent:", "  Construire/modifier un agent :"),
    "agent.build_via_ui": (
        "   - UI: start the web server (bouzequi2), “Agents” tab "
        "(tools/skills/hooks + prompt)",
        "   - UI : lance le serveur web (bouzequi2), onglet « Agents » "
        "(tools/skills/hooks + prompt)",
    ),
    "agent.build_via_meta": (
        "   - or ask the meta agent: /agent meta-agent",
        "   - ou demande à l'agent méta : /agent meta-agent",
    ),
    # --- /agent switching -----------------------------------------------------
    "agent.catalog_refreshed": (
        "Shared agent catalog refreshed.",
        "Catalogue d'agents partagés rafraîchi.",
    ),
    "agent.catalog_refresh_failed": (
        "Catalog refresh failed: {error}",
        "Échec du rafraîchissement du catalogue : {error}",
    ),
    "agent.reverted_to_default": (
        "Default agent restored (every tool re-enabled, base prompt).",
        "Agent par défaut restauré (tous les tools réactivés, prompt de base).",
    ),
    "agent.unknown": (
        "Unknown agent/profile: {name}. Type /agent for the list.",
        "Agent/profil inconnu : {name}. Tape /agent pour la liste.",
    ),
    "agent.model_summary": ("model {model}", "modèle {model}"),
    "agent.switched": (
        "Switched to agent “{name}”{summary}. "
        "Context kept; the KV cache starts over.",
        "Basculé sur l'agent « {name} »{summary}. "
        "Contexte conservé ; le cache KV repart.",
    ),
    # --- /agent install -------------------------------------------------------
    "agent.catalog_unavailable": (
        "Shared agent catalog unavailable: {error}",
        "Catalogue d'agents partagés indisponible : {error}",
    ),
    "agent.install_usage": (
        "Usage: /agent install <name>. Type /agent for the list.",
        "Usage : /agent install <nom>. Tape /agent pour la liste.",
    ),
    "agent.unknown_in_catalog": (
        "Unknown agent in the catalog: {name}.",
        "Agent inconnu dans le catalogue : {name}.",
    ),
    "agent.available_label": ("  Available: ", "  Disponibles : "),
    "agent.profile_written": (
        "Profile “{name}” written to {destination}.",
        "Profil « {name} » écrit dans {destination}.",
    ),
    "agent.plugin_install_errors": (
        "Errors while installing the plugins:",
        "Erreurs lors de l'installation des plugins :",
    ),
    "agent.plugins_ready": (
        "Required plugins ready ({count}).",
        "Plugins requis prêts ({count}).",
    ),
    "agent.switch_to": ("Switch: /agent {name}", "Bascule : /agent {name}"),
    # --- /agent-upgrade -------------------------------------------------------
    "upgrade.no_profile": ("(none)", "(aucun)"),
    "upgrade.unknown_agent": (
        "Unknown agent: {name}. Available: {available}",
        "Agent inconnu : {name}. Disponibles : {available}",
    ),
    "upgrade.scope_one_agent": ("agent {name}", "l'agent {name}"),
    "upgrade.scope_all_profiles": ("the profiles", "les profils"),
    "upgrade.nothing_required": (
        "No plugin required by {scope}.",
        "Aucun plugin requis par {scope}.",
    ),
    "upgrade.target_one_agent": ("of agent {name}", "de l'agent {name}"),
    "upgrade.target_all_profiles": ("of every profile", "de tous les profils"),
    "upgrade.updating": (
        "Updating {count} plugin(s) {target}...",
        "Mise à jour de {count} plugin(s) {target}...",
    ),
    "upgrade.package_failed": ("  {package}: FAILED: {message}", "  {package} : ÉCHEC : {message}"),
    "upgrade.tools_registered": (
        "Plugin tools re-registered.",
        "Tools de plugins ré-enregistrés.",
    ),
}
