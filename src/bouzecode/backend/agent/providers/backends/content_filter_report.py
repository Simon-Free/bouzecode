# [desc] Diagnostic d'un refus content_filter sur la route chat/completions : un fichier et une ligne de journal, aucune relance à l'identique. [/desc]
"""Refus `content_filter` sur la route `/chat/completions` (gateway_preprod, gateway_openai).

LiteLLM traduit le refus du classifieur en `finish_reason: "content_filter"`. Le backend le
relançait une fois, system aplati. Ablation sur payload réel (session 28738fd0, 2026-10-12) :
le refus est DÉTERMINISTE pour un contexte donné (10/10 à 12/12 aux tours 11 et 12), et la
note n'est plus dans le system (elle est en <working_notes>, côté user) : la relance payait un
appel pour le même refus. Le refus remonte tel quel ; la boucle rejoue le tour avec la note
compactée puis sur la chaîne de repli (agent/refusal_fallback.py).
"""
from __future__ import annotations

import logging

from .completion_diagnostics import dump_degenerate_completion

logger = logging.getLogger(__name__)


def report_content_filter_refusal(*, model: str, provider_label: str, stop_reason,
                                  usage: dict) -> None:
    """Trace le refus : un fichier de diagnostic et une ligne de journal (pas le chat)."""
    dumped = dump_degenerate_completion(
        reason="content_filter_refusal", model=model, provider=provider_label,
        stop_reason=stop_reason, raw_text="", streamed_text="", tool_calls=[],
        usage=usage, events=[],
    )
    logger.warning(
        "%s refused the request (content_filter, nothing produced); not retried as-is "
        "(deterministic for this context): the agent loop replays it with a compacted "
        "note, then on the fallback chain%s",
        provider_label, f" — diagnostic: {dumped}" if dumped else "",
    )
