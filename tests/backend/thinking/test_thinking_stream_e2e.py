# [desc] E2E tests verifying thinking deltas are archived in transcript but stripped from subsequent API requests [/desc]
"""The pure ThinkingStreamParser invariants live (fast) in thinking/*; this file proves
the END-TO-END behaviour through the real pipeline: thinking arrives as genuine
thinking_delta SSE events, is archived in the transcript, and is NOT re-sent on the wire.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _assistant(result):
    return [m for m in result.messages if m.get("role") == "assistant"]


def test_thinking_split_across_deltas_is_fully_archived():
    """Reasoning streamed as several thinking_delta events is reassembled into the block."""
    result = bouzecode(
        ["reason"],
        mock_api=[{"thinking": ["first part ", "second part ", "third"], "text": f"answer.\n{METH}"}],
    )
    content = _assistant(result)[0]["content"]
    assert "<thinking>" in content
    assert "first part second part third" in content


def test_thinking_archived_but_stripped_from_next_turn_wire():
    """Turn 1 reasons; the transcript keeps the <thinking>, but turn 2's request to the API
    carries no <thinking> (reasoning is for us, never re-sent on the wire)."""
    result = bouzecode(
        ["t1", "t2"],
        mock_api=[
            {"thinking": ["secret reasoning"], "text": f"first.\n{METH}"},
            f"second.\n{METH}",
        ],
    )
    # archived
    assert any("secret reasoning" in m["content"] for m in _assistant(result))
    # the turn-2 request body carries no thinking on the wire
    turn2 = result.recorded_requests[1]
    blob = str(turn2.get("system")) + str(turn2.get("messages"))
    assert "<thinking>" not in blob
    assert "secret reasoning" not in blob
