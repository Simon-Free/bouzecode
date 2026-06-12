# [desc] Tests tool enable/disable feature: schema filtering, execution blocking, and /tools commands. [/desc]
"""Tests for tool enable/disable feature in tool_registry."""
from __future__ import annotations

import pytest

from bouzecode.backend.core.tool_registry import (
    ToolDef,
    clear_registry,
    disable_tool,
    enable_tool,
    execute_tool,
    get_all_tools,
    get_tool,
    get_tool_schemas,
    is_enabled,
    list_disabled,
    register_tool,
    reset_disabled,
)


def _make_tool(name: str = "echo", read_only: bool = False) -> ToolDef:
    schema = {
        "name": name,
        "description": f"Test tool ({name})",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    }
    return ToolDef(name=name, schema=schema, func=lambda p, c: p.get("text", "ok"),
                   read_only=read_only, concurrent_safe=True)


@pytest.fixture(autouse=True)
def _clean():
    clear_registry()
    register_tool(_make_tool("Read"))
    register_tool(_make_tool("Write"))
    register_tool(_make_tool("Bash"))
    yield
    clear_registry()


class TestDisableEnable:
    def test_all_enabled_by_default(self):
        assert is_enabled("Read")
        assert is_enabled("Write")
        assert is_enabled("Bash")
        assert list_disabled() == []

    def test_disable_tool(self):
        disable_tool("Bash")
        assert not is_enabled("Bash")
        assert is_enabled("Read")
        assert list_disabled() == ["Bash"]

    def test_enable_tool(self):
        disable_tool("Bash")
        enable_tool("Bash")
        assert is_enabled("Bash")
        assert list_disabled() == []

    def test_disable_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown tool"):
            disable_tool("NonExistent")

    def test_enable_unknown_no_error(self):
        enable_tool("NonExistent")

    def test_disable_idempotent(self):
        disable_tool("Bash")
        disable_tool("Bash")
        assert list_disabled() == ["Bash"]

    def test_reset_disabled(self):
        disable_tool("Bash")
        disable_tool("Read")
        assert len(list_disabled()) == 2
        reset_disabled()
        assert list_disabled() == []
        assert is_enabled("Bash")

    def test_get_tool_returns_handler_even_disabled(self):
        disable_tool("Read")
        tool = get_tool("Read")
        assert tool is not None
        assert tool.func({"text": "hi"}, {}) == "hi"

    def test_list_disabled_sorted(self):
        disable_tool("Write")
        disable_tool("Bash")
        assert list_disabled() == ["Bash", "Write"]


class TestSchemaFiltering:
    def test_disabled_tool_excluded_from_schemas(self):
        all_schemas = get_tool_schemas()
        all_names = {s["name"] for s in all_schemas}
        assert "Bash" in all_names

        disable_tool("Bash")
        filtered = get_tool_schemas()
        filtered_names = {s["name"] for s in filtered}
        assert "Bash" not in filtered_names
        assert "Read" in filtered_names

    def test_enable_restores_schema(self):
        disable_tool("Bash")
        assert "Bash" not in {s["name"] for s in get_tool_schemas()}
        enable_tool("Bash")
        assert "Bash" in {s["name"] for s in get_tool_schemas()}


class TestExecutionBlocking:
    def test_disabled_tool_returns_error(self):
        disable_tool("Bash")
        result = execute_tool("Bash", {"text": "hi"}, config={})
        assert "disabled" in result
        assert "Bash" in result

    def test_enabled_tool_executes(self):
        result = execute_tool("Read", {"text": "hello"}, config={})
        assert result == "hello"


class TestCmdTools:
    def test_list(self, capsys):
        from bouzecode.backend.commands.core.basic import cmd_tools
        cmd_tools("", None, {})
        out = capsys.readouterr().out
        assert "[enabled]" in out
        assert "Read" in out

    def test_disable(self, capsys):
        from bouzecode.backend.commands.core.basic import cmd_tools
        cmd_tools("disable Bash", None, {})
        out = capsys.readouterr().out
        assert "Disabled" in out
        assert not is_enabled("Bash")

    def test_enable(self, capsys):
        from bouzecode.backend.commands.core.basic import cmd_tools
        disable_tool("Bash")
        cmd_tools("enable Bash", None, {})
        out = capsys.readouterr().out
        assert "Enabled" in out
        assert is_enabled("Bash")

    def test_reset(self, capsys):
        from bouzecode.backend.commands.core.basic import cmd_tools
        disable_tool("Bash")
        disable_tool("Read")
        cmd_tools("reset", None, {})
        out = capsys.readouterr().out
        assert "re-enabled" in out
        assert list_disabled() == []

    def test_unknown_tool(self, capsys):
        from bouzecode.backend.commands.core.basic import cmd_tools
        cmd_tools("disable NonExistent", None, {})
        captured = capsys.readouterr()
        assert "Unknown" in captured.out + captured.err
