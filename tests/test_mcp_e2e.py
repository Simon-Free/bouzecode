"""E2E tests for MCP feature: initialize, /mcp list, tool call via conversation."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_SERVER = REPO_ROOT / "tests" / "fake_mcp_server.py"
PYTHON_EXE = r"C:\Users\9605647W\PycharmProjects\calypso\bouzecode\.venv\Scripts\python.exe"


def _make_mcp_config(tmpdir: Path) -> Path:
    """Write a .mcp.json in tmpdir pointing to the fake MCP server."""
    config = {
        "mcpServers": {
            "fake": {
                "command": PYTHON_EXE,
                "args": [str(FAKE_SERVER)],
                "transport": "stdio",
            }
        }
    }
    config_path = tmpdir / ".mcp.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


@pytest.fixture(autouse=True)
def mcp_env(tmp_path, monkeypatch):
    """Setup: reset MCP state, write .mcp.json, chdir to tmpdir."""
    from mcp.tools import reset_mcp
    reset_mcp()  # Clear state from registration.py import-time init
    _make_mcp_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    # Teardown: reset MCP singleton state
    reset_mcp()


class TestMCPInitialize:
    """Test MCP initialization and tool registration."""

    def test_initialize_connects_and_registers_tools(self):
        """initialize_mcp() connects to fake server and registers mcp__fake__echo."""
        from mcp.tools import initialize_mcp
        from bouzecode.backend.core.tool_registry import get_tool

        errors = initialize_mcp()

        # No connection error
        assert errors == {"fake": None}

        # Tool registered in registry
        tool_def = get_tool("mcp__fake__echo")
        assert tool_def is not None
        assert tool_def.name == "mcp__fake__echo"
        assert tool_def.schema["name"] == "mcp__fake__echo"
        assert "[MCP:fake]" in tool_def.schema["description"]
        assert tool_def.read_only is True

    def test_initialize_idempotent(self):
        """Calling initialize_mcp() twice returns cached result."""
        from mcp.tools import initialize_mcp

        errors1 = initialize_mcp()
        errors2 = initialize_mcp()
        assert errors1 == errors2 == {"fake": None}

    def test_mcp_tool_execution(self):
        """Calling the registered MCP tool executes against the fake server."""
        from mcp.tools import initialize_mcp
        from bouzecode.backend.core.tool_registry import get_tool

        initialize_mcp()
        tool_def = get_tool("mcp__fake__echo")
        result = tool_def.func({"message": "hello world"}, {})
        assert result == "hello world"

    def test_mcp_tool_error_on_missing_param(self):
        """MCP tool returns error when required param is missing."""
        from mcp.tools import initialize_mcp
        from bouzecode.backend.core.tool_registry import get_tool

        initialize_mcp()
        tool_def = get_tool("mcp__fake__echo")
        result = tool_def.func({"wrong_param": "oops"}, {})
        assert "[MCP tool error]" in result
        assert "Missing required parameter" in result


class TestMCPCmd:
    """Test /mcp command shim."""

    def test_mcp_list_shows_connected_server(self):
        """cmd_mcp('list', ...) shows the fake server as connected with 1 tool."""
        from mcp.tools import initialize_mcp
        from bouzecode.backend.commands.oss_shims.mcp_cmd import cmd_mcp

        initialize_mcp()
        output = cmd_mcp("list", {})

        assert output is not None
        assert "fake" in output
        assert "1 tool(s)" in output
        # Connected icon
        assert "\u2713" in output

    def test_mcp_list_no_servers(self, tmp_path, monkeypatch):
        """cmd_mcp('list', ...) when no servers configured."""
        from mcp.tools import reset_mcp
        reset_mcp()
        # Remove the .mcp.json
        mcp_json = tmp_path / ".mcp.json"
        if mcp_json.exists():
            mcp_json.unlink()

        from bouzecode.backend.commands.oss_shims.mcp_cmd import cmd_mcp
        output = cmd_mcp("list", {})
        # Returns None (info printed to console)
        assert output is None


class TestMCPConversation:
    """Test MCP tool call via e2e conversation harness."""

    def test_mcp_tool_call_in_conversation(self):
        """MockLLM calls mcp__fake__echo and gets the result back."""
        from mcp.tools import initialize_mcp
        from tests.e2e_harness import bouzecode
        from tests.fake_llm import MockLLM

        initialize_mcp()

        mock = MockLLM([
            '<tool_use name="mcp__fake__echo" id="t1"><param name="message">hello world</param></tool_use>',
            "The echo tool returned: hello world",
        ])

        result = bouzecode(["call the echo tool"], mock_llm=mock)

        # The LLM was called a second time — the tool result "hello world"
        # should appear in the messages sent to it on the 2nd call.
        assert len(mock.recorded_calls) >= 2, f"Expected >=2 LLM calls, got {len(mock.recorded_calls)}"
        second_call_messages = str(mock.recorded_calls[1])
        assert "hello world" in second_call_messages, (
            f"Expected 'hello world' in second LLM call messages, got: {second_call_messages[:500]}"
        )
        # Final reply contains the echo result
        assert "hello world" in result.last_reply

    def test_mcp_tool_error_in_conversation(self):
        """MockLLM calls mcp__fake__echo with bad params, gets error, conversation continues."""
        from mcp.tools import initialize_mcp
        from tests.e2e_harness import bouzecode
        from tests.fake_llm import MockLLM

        initialize_mcp()

        mock = MockLLM([
            '<tool_use name="mcp__fake__echo" id="t1"><param name="wrong">oops</param></tool_use>',
            "The tool had an error.",
        ])

        result = bouzecode(["call echo badly"], mock_llm=mock)

        # The tool error should be in the messages fed back to the LLM
        assert len(mock.recorded_calls) >= 2, f"Expected >=2 LLM calls, got {len(mock.recorded_calls)}"
        second_call_messages = str(mock.recorded_calls[1])
        assert "unknown parameter(s)" in second_call_messages or "MCP tool error" in second_call_messages, (
            f"Expected error in second LLM call, got: {second_call_messages[:500]}"
        )
        # Final reply acknowledges the error
        assert "error" in result.last_reply.lower()
