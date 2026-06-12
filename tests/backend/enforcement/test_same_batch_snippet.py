# [desc] Tests that Snippet in the same batch as Read correctly suppresses enforcement of unsnippeted reads. [/desc]
"""Bug reproduction: when Read and Snippet are in the same assistant message (same
batch), get_unsnippeted_reads() should return [] because the Snippet covers the Read.

Currently it returns the Read as uncovered because the coverage scan starts AFTER
the assistant message containing the Read (messages[last_assistant_idx + 1:]),
missing Snippet calls in the SAME message.
"""
import types

import pytest

from bouzecode.backend.tools.enforcement_hooks import get_unsnippeted_reads
from bouzecode.backend.core.tool_registry import (
    ToolDef, register_tool, push_local_overlay, pop_local_overlay,
)


@pytest.fixture
def tools():
    push_local_overlay()
    register_tool(ToolDef(
        name="Read", func=lambda p, c: "",
        schema={"name": "Read", "input_schema": {"type": "object",
                "properties": {"file_path": {"type": "string"}}}}))
    register_tool(ToolDef(
        name="Snippet", func=lambda p, c: "ok",
        schema={"name": "Snippet", "input_schema": {"type": "object", "properties": {
                "file_path": {"type": "string"}, "tool_id": {"type": "string"},
                "ranges": {"type": "array"}, "discard": {"type": "boolean"},
                "label": {"type": "string"}}}}))
    register_tool(ToolDef(
        name="Methodology", func=lambda p, c: "ok",
        schema={"name": "Methodology", "input_schema": {"type": "object",
                "properties": {"content": {"type": "string"}}}}))
    yield
    pop_local_overlay()


def test_read_and_snippet_same_batch_not_enforced(tools):
    """Read + Snippet(file_path=same) in one assistant msg → no unsnippeted reads."""
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}},
            {"id": "s1", "name": "Snippet", "input": {
                "file_path": "a.py", "ranges": [[1, 1]], "label": "x"}},
        ]},
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "x=1\ny=2"},
        {"role": "tool", "tool_call_id": "s1", "name": "Snippet", "content": "ok"},
    ]
    result = get_unsnippeted_reads(messages)
    assert result == [], (
        f"Expected no unsnippeted reads (Snippet in same batch covers Read), got: {result}"
    )


def test_read_and_snippet_discard_same_batch(tools):
    """Read + Snippet(discard=true, file_path=...) in same batch → no enforcement."""
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "b.py"}},
            {"id": "s1", "name": "Snippet", "input": {
                "file_path": "b.py", "discard": True}},
        ]},
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "line1"},
        {"role": "tool", "tool_call_id": "s1", "name": "Snippet", "content": "ok"},
    ]
    result = get_unsnippeted_reads(messages)
    assert result == [], (
        f"Expected no unsnippeted reads (discard in same batch), got: {result}"
    )


def test_read_without_snippet_same_batch_still_enforced(tools):
    """Read alone, model responds WITHOUT Snippet at next turn → should report unsnippeted."""
    big_content = "\n".join(f"line {i}" for i in range(60))  # >= 50 lines
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "c.py"}},
            {"id": "m1", "name": "Methodology", "input": {"content": "notes"}},
        ]},
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": big_content},
        {"role": "tool", "tool_call_id": "m1", "name": "Methodology", "content": "ok"},
        # Model responds at next turn WITHOUT Snippet → enforcement legitimate
        {"role": "assistant", "content": "I did stuff", "tool_calls": [
            {"id": "m2", "name": "Methodology", "input": {"content": "more notes"}},
        ]},
        {"role": "tool", "tool_call_id": "m2", "name": "Methodology", "content": "ok"},
    ]
    result = get_unsnippeted_reads(messages)
    assert len(result) == 1, f"Expected 1 unsnippeted read, got: {result}"
    assert result[0]["file_path"] == "c.py"


def test_read_without_subsequent_turn_not_enforced(tools):
    """Read in current turn, NO subsequent assistant turn → should NOT enforce.

    This is the core bug: enforcement fires immediately after tool execution,
    before the model has a chance to respond with Snippet at its next turn.
    """
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "e.py"}},
            {"id": "m1", "name": "Methodology", "input": {"content": "notes"}},
        ]},
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "x=1\ny=2"},
        {"role": "tool", "tool_call_id": "m1", "name": "Methodology", "content": "ok"},
        # NO subsequent assistant message — model hasn't had its next turn yet
    ]
    result = get_unsnippeted_reads(messages)
    assert result == [], (
        f"Expected no enforcement (model hasn't had next turn yet), got: {result}"
    )


def test_read_covered_by_later_assistant_still_works(tools):
    """Read in batch N, Snippet in batch N+1 → no enforcement (existing behavior)."""
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "d.py"}},
        ]},
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "data"},
        # Next turn covers it
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "s1", "name": "Snippet", "input": {
                "file_path": "d.py", "ranges": [[1, 1]], "label": "d"}},
        ]},
        {"role": "tool", "tool_call_id": "s1", "name": "Snippet", "content": "ok"},
    ]
    result = get_unsnippeted_reads(messages)
    assert result == [], f"Expected covered by later assistant, got: {result}"
