"""Summarize overflowed thinking via a lightweight side-call.

When the model's thinking block exceeds the overflow limit and gets cut,
this module summarizes the lost reasoning so it can be re-injected at
the next turn — avoiding costly re-derivation.

Feature flag: BOUZECODE_THINKING_SUMMARY (default "1", set "0" to disable).
"""

from __future__ import annotations

import logging
import os

from .providers import AssistantTurn
from .stream_interceptor import get_streamer

log = logging.getLogger(__name__)

# Minimum chars of cut thinking before we bother summarizing.
_MIN_CHARS_FOR_SUMMARY = 4000

_SUMMARY_SYSTEM = (
    "Le texte suivant est un raisonnement (thinking) coupé car trop long. "
    "Liste les CONCLUSIONS FINALES auxquelles il est arrivé (en FR) : conclusions "
    "atteintes, décisions prises, faits clés découverts, et la prochaine action "
    "envisagée. Résume librement, dans le format que tu juges le plus clair, sans "
    "limite de longueur imposée mais sans délayer. Pas de préambule, pas de "
    "reformulation de l'énoncé."
)


def summarize_overflow(thinking_text: str, config: dict) -> str | None:
    """Summarize overflowed thinking text via a side-call.

    Returns the summary string, or None if:
    - thinking_text is too short (< _MIN_CHARS_FOR_SUMMARY)
    - feature flag is disabled
    - side-call fails for any reason
    """
    if len(thinking_text) < _MIN_CHARS_FOR_SUMMARY:
        return None

    if os.environ.get("BOUZECODE_THINKING_SUMMARY", "1") == "0":
        return None

    try:
        return _do_summarize(thinking_text, config)
    except Exception:
        log.warning("thinking_summary side-call failed", exc_info=True)
        return None


def _do_summarize(thinking_text: str, config: dict) -> str | None:
    """Perform the actual side-call."""
    side_config = dict(config)
    side_config["_depth"] = 1
    side_config["_context_state"] = None
    # Free-form conclusions need room — 300 would re-truncate the summary itself.
    side_config["max_tokens"] = 1024
    # No tools — pure text completion
    side_config.pop("_tool_choice", None)

    _stream = get_streamer()

    result_text: str | None = None
    for ev in _stream(
        model="claude-sonnet-4-6",
        system=_SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": thinking_text}],
        tool_schemas=[],
        config=side_config,
    ):
        if isinstance(ev, AssistantTurn):
            result_text = ev.text

    if result_text and result_text.strip():
        return result_text.strip()
    return None
