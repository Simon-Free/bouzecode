# [desc] Classifies a user task as feature/bug/autre via a single lightweight LLM call at session start. [/desc]
from __future__ import annotations

import logging
from typing import Generator

logger = logging.getLogger(__name__)

_CLASSIFICATION_SYSTEM_PROMPT = (
    "Classify the user's request. Reply with exactly TWO words, nothing else:\n"
    "1st word — feature, bug, or autre.\n"
    "2nd word — borne (the request states exactly what to do: explicit files/"
    "content, even multi-file), exploratoire (existing code must be understood "
    "first to know what to change), or doute (unsure)."
)

_MAX_USER_CHARS = 2000
_MAX_TOKENS = 12


def _get_dispatch_stream():
    """Lazy import of dispatch.stream — separate function for easy patching."""
    from .providers.backends.dispatch import stream
    return stream


# Module-level reference for patching in tests
dispatch_stream = None  # set lazily


_FALLBACK = {"type": "autre", "scope": "doute"}


def classify_task(user_message: str, config: dict) -> str:
    """Back-compat wrapper: the feature/bug/autre axis only."""
    return classify(user_message, config)["type"]


def classify(user_message: str, config: dict) -> dict:
    """Classify user_message on two axes with ONE ultra-light LLM call:
    type (feature/bug/autre — picks the TDD profile) and scope (borné/
    exploratoire/doute — drives model routing: borné→flash, exploratoire→opus,
    doute→escalade). Gated by config['task_classification'] (default True at
    depth 0). Any failure returns {'type': 'autre', 'scope': 'doute'} with a
    warning log."""
    global dispatch_stream

    # Gate: disabled by config or non-zero depth
    if not config.get("task_classification", True):
        return dict(_FALLBACK)
    if config.get("_depth", 0) > 0:
        return dict(_FALLBACK)

    truncated = user_message[:_MAX_USER_CHARS]
    messages = [{"role": "user", "content": truncated}]

    try:
        model = config.get("model", "")
        if not model:
            logger.warning("task_classifier: no model in config, defaulting to %s", _FALLBACK)
            return dict(_FALLBACK)

        # Resolve stream function (lazy, patchable)
        stream_fn = dispatch_stream or _get_dispatch_stream()

        # Collect text from the stream (no tools, minimal response).
        # thinking_mode "off" is required: with reasoning enabled, deepseek
        # models burn the whole _MAX_TOKENS budget on reasoning and return an
        # empty answer (finish_reason "length") — classification always "autre".
        response_text = _collect_stream_text(
            stream_fn(
                model=model,
                system=_CLASSIFICATION_SYSTEM_PROMPT,
                messages=messages,
                tool_schemas=[],
                config={**config, "max_tokens": _MAX_TOKENS, "task_classification": False,
                    "_depth": 1, "_context_state": None, "thinking_mode": "off"},
            )
        )
        return {"type": _parse_classification(response_text),
                "scope": _parse_scope(response_text)}
    except Exception as exc:
        logger.warning("task_classifier: classification failed (%s), defaulting to %s",
                       exc, _FALLBACK)
        return dict(_FALLBACK)


def _collect_stream_text(gen: Generator) -> str:
    """Consume stream generator and collect text chunks."""
    parts: list[str] = []
    for event in gen:
        if hasattr(event, "text"):
            parts.append(event.text)
        elif isinstance(event, str):
            parts.append(event)
    return "".join(parts)


def _parse_classification(text: str) -> str:
    """Parse LLM response to extract classification. Tolerant matching."""
    lower = text.lower().strip()
    if "feature" in lower:
        return "feature"
    if "bug" in lower:
        return "bug"
    return "autre"


def _parse_scope(text: str) -> str:
    """Tolerant scope parsing (accent-insensitive: borne/borné)."""
    lower = text.lower().strip()
    if "born" in lower:
        return "borné"
    if "explor" in lower:
        return "exploratoire"
    return "doute"
