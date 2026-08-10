# [desc] End-to-end thinking coverage via mock_api: thinking streamed as real SSE thinking_delta is archived, then stripped from the next turn's wire payload. [/desc]
"""The pure ThinkingStreamParser invariants live (fast) in thinking/*; this file proves
the END-TO-END behaviour through the real pipeline: thinking arrives as genuine
thinking_delta SSE events, is archived in the transcript, and is NOT re-sent on the wire.
"""
from __future__ import annotations

import sys

import pytest

from tests.e2e_harness import bouzecode

# Same guard as the sibling mock_api suites (providers/test_mock_api_e2e.py,
# providers/test_resilience_mock_api_e2e.py, xml_protocol/test_xml_stream_e2e.py):
# threaded werkzeug + httpx streaming dead-locks on Windows (reader thread hangs on
# a socket that never EOFs), which wedges the whole worker and makes any full-suite
# run unreadable. Runs on Linux CI.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mock_api e2e hangs on Windows (threaded werkzeug + httpx streaming)",
)


def _assistant(result):
    return [m for m in result.messages if m.get("role") == "assistant"]


def test_thinking_split_across_deltas_is_fully_archived():
    """Reasoning streamed as several thinking_delta events is reassembled into the block."""
    result = bouzecode(
        ["reason"],
        # Plain text, no tool call — that is what closes a session. A Methodology-only
        # batch is bookkeeping and earns a continue-nudge (which here would exhaust
        # the mock server and hang the real client on retried 500s).
        mock_api=[{"thinking": ["first part ", "second part ", "third"], "text": "answer."}],
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
            {"thinking": ["secret reasoning"], "text": "first."},
            "second.",
        ],
    )
    # archived
    assert any("secret reasoning" in m["content"] for m in _assistant(result))
    # the turn-2 request body carries no thinking on the wire
    turn2 = result.recorded_requests[1]
    blob = str(turn2.get("system")) + str(turn2.get("messages"))
    assert "<thinking>" not in blob
    assert "secret reasoning" not in blob
