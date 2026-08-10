# [desc] Feature test: an overflow must summarize+persist the cut reasoning to methodology in BOTH loud (TextChunk) and extended (ThinkingChunk) modes. [/desc]
"""Overflow summary persistence across thinking modes.

Reproduces the BR-refacto loop seen live with opus-4-6: the thinking overflow
fired but ZERO "Auto-compacted thoughts after overflow" blocks were written to
the methodology, so the model lost its conclusions and re-derived them every
turn (re-fetching the 90 KB BR + 74 KB doc), never reaching final_answer.

Root cause: the host app runs in LOUD thinking mode — the reasoning is streamed as
visible TextChunk (-> ctx.text_parts), not ThinkingChunk (-> ctx.thinking_parts).
The overflow handler summarized "".join(ctx.thinking_parts) only, which is empty
in loud mode, so summarize_overflow saw <4000 chars and returned None.

These tests drive a real bouzecode() conversation with a mocked LLM:
- the overflow turn streams a large reasoning blob (loud or extended),
- the summarize side-call (run at _depth=1) is served by MockLLM.side_call_response,
- we assert the unique "Auto-compacted thoughts after overflow" header lands in
  the durable methodology note (context_state.notes).
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

_METH = '<tool_use name="Methodology" id="m1"><param name="content">noted</param></tool_use>'

# Loud reasoning: plain prose, NO tool/think/backtick markup, so MockLLM streams
# it as a single TextChunk that lands in ctx.text_parts. ~10 KB > overflow limit
# (6000) AND > the 4000-char summary floor.
_LOUD = "Analyse de la BR: la variable counter est modifiee plus de deux fois par passe. " * 130

_SUMMARY = (
    "CONCLUSIONS: counter et offre_promo sont modifiees plus de 2 fois; "
    "prochaine action = ecrire le DSM regroupe."
)
_OVERFLOW_HEADER = "Auto-compacted thoughts after overflow"


def test_loud_mode_overflow_summary_is_persisted():
    """LOUD mode (reasoning in TextChunk) — the bug. Fails before the fix."""
    assert len(_LOUD) > 8000
    mock = MockLLM([
        _LOUD,                                   # turn 1: huge loud reasoning, no tool -> overflow
        # Turn 2 (post-nudge): plain text, no tool call — that is what closes.
        "Voici le DSM corrige.",
    ])
    mock.side_call_response = _SUMMARY

    result = bouzecode(
        ["Refactore cette BR"],
        mock_llm=mock,
        config_overrides={"thinking_overflow_limit": 6000, "_enforce_tests": False},
    )

    meth = result.state.context_state.notes.get("methodology", "")
    assert _OVERFLOW_HEADER in meth, (
        "loud-mode overflow did not persist its summary to methodology — "
        f"meth={meth!r}"
    )
    assert "prochaine action" in meth


def test_extended_mode_overflow_summary_is_persisted():
    """EXTENDED mode (reasoning in ThinkingChunk) — regression guard: the fix
    concatenates both buffers, so this path must keep working."""
    mock = MockLLM([
        {"thinking": ["x" * 10000], "text": ""},  # turn 1: huge API thinking -> overflow
        "Done.",
    ])
    mock.side_call_response = _SUMMARY

    result = bouzecode(
        ["go"],
        mock_llm=mock,
        config_overrides={"thinking_overflow_limit": 6000, "_enforce_tests": False},
    )

    meth = result.state.context_state.notes.get("methodology", "")
    assert _OVERFLOW_HEADER in meth, f"extended-mode overflow regressed — meth={meth!r}"
