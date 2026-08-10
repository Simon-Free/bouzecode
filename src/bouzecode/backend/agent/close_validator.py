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
    "et concrète de ce qui manque. Rien d'autre.\n\n"
    "ARTEFACTS DE TRAVAIL — NE PAS rendre KO là-dessus : (a) les fichiers écrits "
    "en `temp=True` vivent dans un scratch dir HORS du worktree git (jamais trackés, "
    "jamais committables, détruits en fin de session) — ils n'apparaissent donc "
    "JAMAIS dans un diff ; (b) le lock d'orchestration `.agents.lock` est exclu "
    "automatiquement du commit par le harvest de merge — il ne peut pas polluer la "
    "livraison. Ne réclame donc pas leur suppression et ne bloque pas sur leur "
    "présence supposée : le staging de merge s'en charge déjà."
)

_MAX_TOKENS = 200
_MAX_SECTION_CHARS = 6000

# Module-level reference for patching in tests (same pattern as task_classifier).
dispatch_stream = None


_RECAP_SECTION_MARKERS = ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.")


def missing_recap_sections(answer: str) -> list[str]:
    """Deterministic (no LLM) check that the FinalAnswer carries the 6 mandatory
    recap section headers `## 1.` .. `## 6.`. Returns the list of missing markers."""
    text = answer or ""
    return [m for m in _RECAP_SECTION_MARKERS if m not in text]


# Retry cap for the structured-recap gate: after this many refusals the close is
# ACCEPTED anyway (with recap_missing=True) so a session is never bricked forever.
RECAP_RETRY_CAP = 3


def missing_recap_fields(recap: object, coding: bool) -> list[str]:
    """Deterministic (no LLM) check that the structured `recap` object carries the
    mandatory fields. Coding sessions require symptoms/explanation/tests/changes
    (changes non-empty, each item carrying file+summary). Non-coding sessions
    (study/question) only require symptoms/explanation. Returns missing-field labels."""
    if not isinstance(recap, dict):
        base = ["symptoms", "explanation"]
        return base + (["tests", "changes"] if coding else [])
    missing: list[str] = []
    for field_name in ("symptoms", "explanation"):
        if not str(recap.get(field_name, "")).strip():
            missing.append(field_name)
    if not coding:
        return missing
    if not str(recap.get("tests", "")).strip():
        missing.append("tests")
    changes = recap.get("changes")
    if not isinstance(changes, list) or not changes:
        missing.append("changes")
    else:
        for i, item in enumerate(changes):
            if not isinstance(item, dict) or not str(item.get("file", "")).strip() \
                    or not str(item.get("summary", "")).strip():
                missing.append(f"changes[{i}].file+summary")
    return missing


def _should_validate(config: dict) -> bool:
    if not config.get("close_validation", True):
        return False
    if config.get("_depth", 0) > 0:
        return False
    from .providers.registry import model_uses_native_tools
    return model_uses_native_tools(config.get("model", ""), config)


def validate_close(answer: str, config: dict, recap: object = None) -> tuple[bool, str]:
    """Return (accepted, feedback). Accepts on any failure, with a warning log.

    When `recap` (a structured object) is provided the deterministic gate validates
    that OBJECT (symptoms/explanation/tests/changes). When it is absent the gate
    falls back to the legacy 6-section markdown check on `answer` (backward compat).
    A retry cap (RECAP_RETRY_CAP) prevents bricking a session forever: past the cap
    the close is accepted and config['_recap_missing'] is flagged."""
    # Deterministic recap gate (no LLM): profiles that set require_recap MUST
    # deliver a complete recap. Checked BEFORE the native-model LLM gate so it
    # applies regardless of the model backend.
    if (
        config.get("close_validation", True) is not False
        and config.get("require_recap")
        and config.get("_depth", 0) == 0
    ):
        coding = config.get("recap_coding", True)
        if recap is not None or config.get("recap_expects_object"):
            missing = missing_recap_fields(recap, coding)
            label = "champs manquants"
        else:
            missing = missing_recap_sections(answer)
            label = "sections manquantes"
        if missing:
            retries = int(config.get("_recap_retry_count", 0)) + 1
            config["_recap_retry_count"] = retries
            if retries > RECAP_RETRY_CAP:
                # Never brick a session: accept after the cap, flag recap as missing.
                config["_recap_missing"] = True
                logger.warning(
                    "close_validator: recap still incomplete after %d retries "
                    "(%s: %s) — accepting close with recap_missing=True",
                    retries - 1, label, " ; ".join(missing),
                )
                return True, ""
            return False, (
                f"récap incomplet — {label} : " + " ; ".join(missing)
            )
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
