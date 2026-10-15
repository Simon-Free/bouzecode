# [desc] Outils de la flotte gouvernée : Fleet (lister / tuer les agents web, ou la flotte du TUI) et ListAgentTypes (les typologies dispatchables). [/desc]
"""Vue d'ensemble pour un manager : quels agents tournent, et quels types il peut lancer."""
from __future__ import annotations

import os

from .appel_agent import _MANAGER_FORBIDDEN_TYPES


def _list_agent_types(params: dict, config: dict) -> str:
    """List agent typologies from the SAME source of truth as GET /api/typologies
    (project-local + global + extra profiles + builtin system agents), so a manager
    dispatched in the web UI enumerates exactly the kanban's typologies."""
    from bouzecode.web_v2.services.typologies import list_typologies
    typologies = list_typologies(project_path=os.getcwd())
    # 'general-purpose' / 'default' are NEVER listed by ListAgentTypes, regardless
    # of the caller: they are the generic un-scoped agents and must never be
    # proposed as a dispatchable typology (the specialized 'coder' is the default
    # coding agent instead).
    typologies = [t for t in typologies
                  if (t.get("name") or "").strip().lower() not in _MANAGER_FORBIDDEN_TYPES]
    if not typologies:
        return "No agent types available."
    lines = ["Available agent types (use the name as subagent_type):", ""]
    for t in typologies:
        desc = (t.get("description") or "").strip().split("\n", 1)[0]
        lines.append(f"  {t['name']:20s}  {desc}")
        if t.get("default_model"):
            lines.append(f"                        model: {t['default_model']}")
    lines.append("")
    lines.append(
        "Create custom agents: write a profile YAML in ~/.bouzecode/profiles/ "
        "or <project>/.bouzecode/profiles/ (see the meta-agent / creating-agents skill)."
    )
    return "\n".join(lines)


def _fleet_tool(params: dict, config: dict) -> str:
    """Manager fleet control WITHOUT shell/HTTP: lists or kills governed web agents by
    calling the Python services directly (web_v2.services.work.fleet + web_v2.runtime.runner).

    action="list"  → agent_tree() rendered as readable text (agent_id, state, project…).
    action="kill"  → requires agent_id; resolves the live Agent via agent_registre.list_agents()
                     and calls agent_arret.kill_agent(agent). Clear message if not found.
    Only available in bouzeui web mode (there is a governed ticket fleet there)."""
    from ..tools.interaction import is_web_ipc_active
    if not is_web_ipc_active() and config.get("_tui_agents") is not None:
        from .en_process.outil import flotte_tui  # sous-agents du TUI, en process
        return flotte_tui(params, config)
    if not is_web_ipc_active():
        return ("Fleet n'est disponible qu'en mode bouzeui web (il pilote la flotte de "
                "tickets gouvernés). Hors web, il n'y a pas de flotte à lister/tuer.")

    action = (params.get("action") or "").strip().lower()
    if action not in ("list", "kill"):
        return "Fleet: 'action' doit valoir 'list' ou 'kill'."

    from ...web_v2.runtime.runner import agent_arret, agent_registre
    from ...web_v2.services.work import fleet

    if action == "list":
        nodes = fleet.agent_tree().get("nodes", [])
        if not nodes:
            return "Aucun agent dans la flotte."
        lines = [f"{len(nodes)} agent(s) :"]
        for n in nodes:
            flags = []
            if n.get("suspect_dead"):
                flags.append("suspect_dead")
            if n.get("question"):
                flags.append("waiting_question")
            flag_txt = f" [{', '.join(flags)}]" if flags else ""
            parent = n.get("parent") or "-"
            lines.append(
                f"- {n.get('agent_id', '?')} | {n.get('state', '?')} | "
                f"projet={n.get('project_name') or n.get('project_slug') or '?'} | "
                f"parent={parent} | {n.get('title') or ''}{flag_txt}"
            )
        return "\n".join(lines)

    # action == "kill"
    agent_id = (params.get("agent_id") or "").strip()
    if not agent_id:
        return "Fleet kill: 'agent_id' requis."
    target = next((a for a in agent_registre.list_agents() if a.agent_id == agent_id), None)
    if target is None:
        return f"Fleet kill: agent introuvable (agent_id={agent_id}). Utilise action='list'."
    agent_arret.kill_agent(target)
    #  Arrêté par décision : aucun réveil automatique ne doit le relancer ensuite.
    from bouzecode.web_v2.services.work import arret
    arret.demander(target, "Fleet kill")
    return f"Agent {agent_id} tué (kill demandé)."
