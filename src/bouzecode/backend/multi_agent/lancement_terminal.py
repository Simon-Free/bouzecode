# [desc] Chemin terminal de l'outil Agent : lance le sous-agent dans une nouvelle fenêtre (`bouzecode -p --result-file`), le fait suivre par un thread, et l'attend ou rend la main. [/desc]
"""`Agent` quand bouzecode tourne dans un vrai terminal (tty, pas d'IPC web)."""
from __future__ import annotations

import os

from .appel_agent import _attend_l_enfant, _gate_hors_process


# Wait-loop tuning for terminal sub-agents. Module-level so tests can monkeypatch.
_TERMINAL_WAIT_TIMEOUT = 300
_TERMINAL_WAIT_INTERVAL = 2
_TERMINAL_SIGNE_DE_VIE_S = 60.0  # sans PID écrit passé ce délai : lancement raté


def _spawn_terminal_agent(params: dict, config: dict) -> str:
    """Spawn sub-agent in a new terminal window and optionally wait for result."""
    refus = _gate_hors_process(config)
    if refus is not None:
        return refus
    import tempfile
    from .gestionnaire import get_agent_manager
    from .terminal import spawn_in_terminal

    mgr = get_agent_manager()
    prompt = params["prompt"]
    wait = _attend_l_enfant(params)
    name = params.get("name", "")
    subagent_type = params.get("subagent_type", "")
    model_override = params.get("model", "")

    # Build effective config for the sub-agent process
    eff_config = {k: v for k, v in config.items() if not k.startswith("_")}
    if model_override:
        eff_config["model"] = model_override
    # Re-inject the keep-open debug flag (stripped above because it starts with "_")
    if config.get("_terminal_keep_open"):
        eff_config["_terminal_keep_open"] = True

    # Create task for tracking
    task = mgr.create_task(prompt=prompt, depth=config.get("_depth", 0), name=name)
    if subagent_type:
        task.agent_type = subagent_type
    task.model = eff_config.get("model", "")
    task.status = "running"
    from .enfants import noter_enfant_local
    noter_enfant_local(config, task.id)

    # Result file for inter-process communication
    result_file = os.path.join(tempfile.gettempdir(), f"bouzecode_agent_{task.id}.result.txt")

    from .profondeur import env_enfant
    from .surveillance_terminal import surveiller
    spawn_in_terminal(prompt, result_file, eff_config, env_extra=env_enfant(config))
    #  Un thread relève résultat, fiche ou mort de l'enfant et tient task.status à jour : en
    #  arrière-plan comme en pause (avant, un enfant en arrière-plan restait « running »).
    surveiller(task, result_file, _TERMINAL_WAIT_INTERVAL,
               delai_signe_de_vie_s=_TERMINAL_SIGNE_DE_VIE_S)

    if not wait:
        info_parts = [
            f"Task ID: {task.id}",
            f"Name: {task.name}",
            "Status: running (in new terminal)",
        ]
        if subagent_type:
            info_parts.append(f"Type: {subagent_type}")
        info_parts.append(f"Result file: {result_file}")
        info_parts.append("The agent is running in a separate terminal window.")
        return "\n".join(info_parts)

    # Wait mode: the child writes its FinalAnswer to the result file, or only its close fiche
    # when it ended without delivering (see resultat_terminal). Past the delay it is NOT
    # declared failed: it lives on, still followed.
    mgr.wait(task.id, timeout=_TERMINAL_WAIT_TIMEOUT)
    result = task.result
    if task.status in ("pending", "running"):
        result = (f"Toujours actif après {_TERMINAL_WAIT_TIMEOUT}s (task_id={task.id}) : il "
                  "continue, suivi par le harnais. Attends-le avec CheckAgentResult(task_id="
                  f"'{task.id}', wait=true) ou arrête-le avec CheckAgentResult(task_id="
                  f"'{task.id}', arreter=true) ; ne le relance pas.")

    header = f"[Agent (terminal): {task.name}"
    if subagent_type:
        header += f" ({subagent_type})"
    header += "]"
    return f"{header}\n\n{result or '(no output)'}"
