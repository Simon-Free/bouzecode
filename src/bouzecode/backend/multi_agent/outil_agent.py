# [desc] Outil `Agent` : garde-fous communs, puis aiguillage vers le TUI en process, la fenêtre de terminal, le ticket web, ou à défaut un thread du SubAgentManager. [/desc]
"""Point d'entrée de l'outil `Agent`. Les chemins de lancement sont importés À L'APPEL :
un test qui remplace `lancement_terminal._spawn_terminal_agent` ou
`lancement_web._spawn_web_ticket_agent` est donc vu ici."""
from __future__ import annotations

import sys

from ..core.tool_registry import inherit_private
from .appel_agent import _attend_l_enfant, _gate_hors_process, _manager_type_guard


def _is_terminal_mode() -> bool:
    """True when bouzecode is running in a real terminal (not bouzeui)."""
    from ..tools.interaction import is_web_ipc_active
    return not is_web_ipc_active() and sys.stdin.isatty()


def _agent_tool(params: dict, config: dict) -> str:
    """Spawn a sub-agent, routed by execution context:
      - terminal (tty, no web IPC) → new terminal window;
      - bouzeui web (web IPC active) → governed web TICKET + auto wake-on-completion;
      - pure headless → in-process SubAgentManager thread (fallback).

    Reads from config:
      _system_prompt  — injected by agent.py run(), used as base system prompt
      _depth          — current nesting depth (prevents infinite recursion)
    """
    from ..tools.interaction import is_web_ipc_active

    # Role-based guard FIRST (before any routing/spawn): a manager may only
    # dispatch specialized typologies, never 'general-purpose' / 'default'.
    refusal = _manager_type_guard(config, params.get("subagent_type", ""))
    if refusal is not None:
        return refusal
    # Récursion bornée (config.max_agent_depth) et isolation valide, sur les TROIS chemins.
    from .profondeur import isolation_demandee, refus_profondeur
    refusal = refus_profondeur(config) or isolation_demandee(params)[1]
    if refusal is not None:
        return refusal

    # TUI interactif : sous-agent EN PROCESS, visible dans la barre du bas (le REPL pose le
    # registre ; `subagents_window: true` le retire et rend l'ancienne fenêtre de terminal).
    if config.get("_tui_agents") is not None and not config.get("subagents_window"):
        from .en_process import agent_tui
        return agent_tui(params, config)
    # Auto-dispatch by context: terminal → window, web → governed ticket
    if _is_terminal_mode():
        from .lancement_terminal import _spawn_terminal_agent
        return _spawn_terminal_agent(params, config)
    if is_web_ipc_active():
        from .lancement_web import _spawn_web_ticket_agent
        return _gate_hors_process(config) or _spawn_web_ticket_agent(params, config)

    from .gestionnaire import get_agent_manager
    mgr = get_agent_manager()

    prompt = params["prompt"]
    wait = _attend_l_enfant(params)
    name = params.get("name", "")
    model_override = params.get("model", "")
    subagent_type = params.get("subagent_type", "")

    system_prompt = config.get("_system_prompt", "You are a helpful assistant.")
    depth = config.get("_depth", 0)

    # Strip private keys before passing to sub-agent — sauf celles qui DOIVENT suivre,
    # dont le point de contrôle de l'hôte (`_tool_gate`, ).
    eff_config = inherit_private(config, {k: v for k, v in config.items() if not k.startswith("_")})
    if model_override:
        eff_config["model"] = model_override

    # Resolve the agent profile (system builtin or user/project/catalog profile)
    profile = None
    if subagent_type:
        from ..profiles.discovery import resolve_agent_profile
        profile = resolve_agent_profile(subagent_type)
        if profile is None:
            return (
                f"Error: unknown subagent_type '{subagent_type}'. "
                "Use ListAgentTypes to see available types."
            )

    task = mgr.spawn(
        prompt, eff_config, system_prompt,
        depth=depth,
        profile=profile,
        # Environnement : celui demandé par le parent (`isolation`), sinon partagé — l'enfant
        # appelle alors `Environment(action='worktree')` s'il découvre qu'il va écrire.
        isolation="worktree" if str(params.get("isolation") or "").startswith("worktree") else "",
        name=name,
    )

    if task.status == "failed":
        return f"Error spawning agent: {task.result}"
    from .enfants import noter_enfant_local
    noter_enfant_local(config, task.id)

    if wait:
        mgr.wait(task.id, timeout=300)
        result = task.result or f"(no output — status: {task.status})"
        header = f"[Agent: {task.name}"
        if subagent_type:
            header += f" ({subagent_type})"
        if task.worktree_branch:
            header += f", branch: {task.worktree_branch}"
        header += "]"
        return f"{header}\n\n{result}"
    else:
        info_parts = [f"Task ID: {task.id}", f"Name: {task.name}", f"Status: {task.status}"]
        if subagent_type:
            info_parts.append(f"Type: {subagent_type}")
        if task.worktree_branch:
            info_parts.append(f"Worktree branch: {task.worktree_branch}")
        info_parts.append("Use CheckAgentResult or SendMessage to interact with this agent.")
        return "\n".join(info_parts)
