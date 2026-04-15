# [desc] Tests sanitization of corrupted or invalid tool names across provider serialization and execution. [/desc]
"""Tests for tool name sanitization (defense against upstream proxy mangling)."""
from __future__ import annotations

import pytest


def test_sanitize_tool_name_valid():
    from providers import sanitize_tool_name
    assert sanitize_tool_name("Write") == ("Write", None)
    assert sanitize_tool_name("mcp__server__tool-1") == ("mcp__server__tool-1", None)


def test_sanitize_tool_name_corrupted_xml():
    from providers import sanitize_tool_name
    bad = 'Write" id="call_1'
    assert sanitize_tool_name(bad) == ("_InvalidToolName", bad)


def test_sanitize_tool_name_empty():
    from providers import sanitize_tool_name
    assert sanitize_tool_name("") == ("_InvalidToolName", "")


def test_sanitize_tool_name_unicode():
    from providers import sanitize_tool_name
    assert sanitize_tool_name("Write\u20ac") == ("_InvalidToolName", "Write\u20ac")


def test_messages_to_anthropic_serializes_tool_call_as_xml():
    """A historical assistant message with a tool_call gets re-serialized as
    XML text (upstream proxies can't mangle plain text)."""
    from providers import messages_to_anthropic
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
    assert isinstance(assistant_msg["content"], str)
    assert '<tool_use name="Write" id="toolu_1">' in assistant_msg["content"]
    assert '<param name="file_path">a.py</param>' in assistant_msg["content"]
    assert "</tool_use>" in assistant_msg["content"]


def test_messages_to_openai_rewrites_bad_tool_name():
    from providers import messages_to_openai
    bad_name = 'Glob" id="call_2'
    history = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_x", "name": bad_name, "input": {"pattern": "*.py"}}],
        },
    ]
    converted = messages_to_openai(history)
    assert converted[0]["tool_calls"][0]["function"]["name"] == "_InvalidToolName"
    import json
    args = json.loads(converted[0]["tool_calls"][0]["function"]["arguments"])
    assert args.get("_corrupted_name") == bad_name


def test_invalid_tool_name_returns_error_to_model():
    from tool_registry import execute_tool
    result = execute_tool("_InvalidToolName", {"_corrupted_name": 'Write" id="call_1'}, {})
    assert "Write" in result
    assert "_InvalidToolName" not in result or "must match" in result.lower() or "invalid" in result.lower()
    assert "retry" in result.lower() or "re-emit" in result.lower() or "re-issue" in result.lower()


def test_invalid_tool_name_auto_permitted():
    from agent import _check_permission
    tc = {"name": "_InvalidToolName", "input": {"_corrupted_name": "x"}, "id": "t1"}
    assert _check_permission(tc, {"permission_mode": "auto"}) is True
