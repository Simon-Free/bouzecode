# [desc] Validates a FinalAnswer close against the Methodology note via one light LLM call (native models). [/desc]
"""Closure gate for cheap native models (deepseek-*): when FinalAnswer is
declared, ONE light LLM call checks the Methodology todolist + the task against
the proposed answer. KO -> the close is refused with the missing items; the
session continues. Best-effort: any infra failure ACCEPTS the close (the
validator must never brick a session). Gated by config['close_validation']
(default True) and only for native tool-calling models at depth 0."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_VALIDATOR_SYSTEM = (
    "Tu valides la clôture d'une session d'agent de code. On te donne la TÂCHE, "
    "la note METHODOLOGY (todolist `[ ]`/`[x]` + découvertes) et la RÉPONSE "
    "FINALE proposée. Réponds sur UNE ligne : « OK » si la tâche est entièrement "
    "réalisée (aucun `[ ]` non justifié, la validation demandée — tests, commande "
    "— a bien été exécutée avec succès) ; sinon « KO: » suivi de la liste courte "
    "et concrète de ce qui manque. Rien d'autre."
)

_MAX_TOKENS = 200
_MAX_SECTION_CHARS = 6000

# Module-level reference for patching in tests (same pattern as task_classifier).
dispatch_stream = None


def _should_validate(config: dict) -> bool:
    if not config.get("close_validation", True):
        return False
    if config.get("_depth", 0) > 0:
        return False
    from .providers.registry import model_uses_native_tools
    return model_uses_native_tools(config.get("model", ""), config)


def validate_close(answer: str, config: dict) -> tuple[bool, str]:
    """Return (accepted, feedback). Accepts on any failure, with a warning log."""
    if not _should_validate(config):
        return True, ""
    state = config.get("_state")
    task = ""
    if state is not None and getattr(state, "messages", None):
        task = str(state.messages[0].get("content", ""))
    from ..context_manager.state import METHODOLOGY_NOTE, resolve_context_state
    cs = resolve_context_state(config)
    methodology = (cs.notes.get(METHODOLOGY_NOTE, "") if cs is not None else "") or ""

    prompt = (
        f"TÂCHE :\n{task[:_MAX_SECTION_CHARS]}\n\n"
        f"METHODOLOGY :\n{methodology[-_MAX_SECTION_CHARS:]}\n\n"
        f"RÉPONSE FINALE PROPOSÉE :\n{answer[:_MAX_SECTION_CHARS]}"
    )
    try:
        stream_fn = dispatch_stream
        if stream_fn is None:
            from .providers.backends.dispatch import stream as stream_fn
        parts = []
        for ev in stream_fn(
            model=config["model"], system=_VALIDATOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}], tool_schemas=[],
            config={**config, "max_tokens": _MAX_TOKENS, "thinking_mode": "off",
                    "task_classification": False, "_depth": 1, "_context_state": None},
        ):
            if hasattr(ev, "text"):
                parts.append(ev.text)
        verdict = "".join(parts).strip()
    except Exception as exc:
        logger.warning("close_validator: validation failed (%s) — accepting close", exc)
        return True, ""
    if verdict.upper().startswith("KO"):
        return False, verdict[2:].lstrip(":— ").strip() or "todolist incomplète"
    return True, ""
