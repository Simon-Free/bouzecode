# [desc] Tests sanitization of corrupted or invalid tool names across provider serialization and execution.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests sanitization of corrupted or invalid tool names across provider serialization and execution.</param></tool_use> [/desc]
"""Tests for tool name sanitization (defense against upstream proxy mangling)."""
from __future__ import annotations

import pytest


def test_sanitize_tool_name_valid():
    from bouzecode.backend.agent.providers import sanitize_tool_name
    assert sanitize_tool_name("Write") == ("Write", None)
    assert sanitize_tool_name("mcp__server__tool-1") == ("mcp__server__tool-1", None)


def test_sanitize_tool_name_corrupted_xml():
    from bouzecode.backend.agent.providers import sanitize_tool_name
    bad = 'Write" id="call_1'
    assert sanitize_tool_name(bad) == ("_InvalidToolName", bad)


def test_sanitize_tool_name_empty():
    from bouzecode.backend.agent.providers import sanitize_tool_name
    assert sanitize_tool_name("") == ("_InvalidToolName", "")


def test_sanitize_tool_name_unicode():
    from bouzecode.backend.agent.providers import sanitize_tool_name
    assert sanitize_tool_name("Write\u20ac") == ("_InvalidToolName", "Write\u20ac")


def test_messages_to_anthropic_serializes_tool_call_as_xml():
    """A historical assistant message with a tool_call gets re-serialized as
    XML text (the SNCF socle proxy can't mangle plain text)."""
    from bouzecode.backend.agent.providers import messages_to_anthropic
    history = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "toolu_1", "name": "Write", "input": {"file_path": "a.py"}}],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "name": "Write", "content": "ok"},
    ]
    converted = messages_to_anthropic(history)
    assistant_msg = converted[1]
    assert assistant_msg["role"] == "assistant"
    content = assistant_msg["content"]
    text = content if isinstance(content, str) else "".join(
        b.get("text", "") for b in content if isinstance(b, dict)
    )
    assert '<tool_use name="Write" id="toolu_1">' in text
    assert '<param name="file_path">a.py</param>' in text
    assert "</tool_use>" in text


def test_invalid_tool_name_returns_error_to_model():
    from bouzecode.backend.core.tool_registry import execute_tool
    result = execute_tool("_InvalidToolName", {"_corrupted_name": 'Write" id="call_1'}, {})
    assert "Write" in result
    assert "_InvalidToolName" not in result or "must match" in result.lower() or "invalid" in result.lower()
    assert "retry" in result.lower() or "re-emit" in result.lower() or "re-issue" in result.lower()


def test_invalid_tool_name_auto_permitted():
    from bouzecode.backend.agent import _check_permission
    tc = {"name": "_InvalidToolName", "input": {"_corrupted_name": "x"}, "id": "t1"}
    assert _check_permission(tc, {"permission_mode": "auto"}) is True
