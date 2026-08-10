# [desc] After an overflow-cut turn, the just-analyzed tool_results (e.g. the uploaded BR) must stay on the next wire — else the model re-fetches, re-overflows, loops. [/desc]
"""Overflow must not orphan the batch the model was reasoning about.

Scenario (mirrors the BR-refacto loop with opus-4-6):
  turn 1 — model fetches a large tool result (the "BR")
  turn 2 — model reasons (loud) about it and overflows BEFORE emitting a tool
  turn 3 — forced to ACT

Bug: the overflow appends an assistant(<thinking>)+user(nudge) AFTER turn 1's
tool_results, so build_minimal_payload no longer sees turn 1's batch as "live"
and drops the BR. Turn 3 receives the nudge + the (summarized) thoughts but NOT
the BR -> the model re-fetches it -> re-overflows -> loops.

Fix: an overflow-cut turn (no tool call this turn) must keep the previous batch's
tool_results live for the next turn, so the model can act on the same material it
was cut while analyzing.

We assert on the actual wire MockLLM received (recorded_calls).
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

_METH = '<tool_use name="Methodology" id="m1"><param name="content">noted</param></tool_use>'
_MARKER = "BRDATA_MARKER_7f3a"
# One-line distinctive "BR" content (single line => never snippet-wrapped, so the
# marker appears verbatim on the wire).
_TOOL_RESULT = _MARKER + " " + ("dsm-line " * 400)
# Loud reasoning: plain prose (no markup) -> one TextChunk -> ctx.text_parts ->
# overflow at the 6000 limit, no tool parsed this turn.
_LOUD = "Je reflechis longuement a la refacto de cette BR sans encore agir. " * 200


def _wire_text(messages) -> str:
    parts = []
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    parts.append(b.get("text", "") or str(b.get("content", "")))
    return "\n".join(parts)


def test_overflow_keeps_just_fetched_tool_results_on_next_wire():
    mock = MockLLM([
        f'{_METH}\n<tool_use name="Bash" id="b1"><param name="command">cat br.json</param></tool_use>',  # turn 1: fetch "BR"
        _LOUD,                                  # turn 2: reason -> overflow (no tool)
        # Turn 3: plain text, no tool call — that is what closes a session.
        "Voici le DSM corrige.",
    ])
    mock.side_call_response = "resume: agir maintenant avec le DSM."

    bouzecode(
        ["Refactore cette BR uploadee"],
        mock_llm=mock,
        mock_tools={"Bash": _TOOL_RESULT},
        config_overrides={"thinking_overflow_limit": 6000, "_enforce_tests": False},
    )

    # Sanity: on the overflow turn (turn 2) the BR result WAS on the wire (live batch).
    assert _MARKER in _wire_text(mock.get_messages(1)), "precondition: BR should be live on turn 2"

    # The fix: turn 3 (right after the overflow cut) must still carry the BR so the
    # model can ACT instead of re-fetching and re-overflowing.
    assert _MARKER in _wire_text(mock.get_messages(2)), (
        "BR tool_result was dropped from the wire after the overflow cut — "
        "the model loses the material it was analyzing and re-fetches it (loop)."
    )
