"""E2E test: Plugin system — list plugins, load a fake plugin with tools."""
from __future__ import annotations

import json

import pytest

from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


@pytest.fixture(autouse=True)
def _isolated_plugin_store(tmp_path, monkeypatch):
    """Point the USER-scoped plugin store at a throwaway dir.

    `plugin.store.list_plugins()` reads `~/.bouzecode/plugins.json`. Left alone,
    these tests parse the developer's own installed plugins — one entry written by
    an older schema was enough to blow the suite up with `KeyError: 'install_dir'`
    on a machine, and pass on another. `monkeypatch.chdir(tmp_path)` only covers
    the PROJECT scope; the user scope needs these two names repointed."""
    import plugin.store as plugin_store
    monkeypatch.setattr(plugin_store, "USER_PLUGIN_DIR", tmp_path / "user_plugins")
    monkeypatch.setattr(plugin_store, "USER_PLUGIN_CFG", tmp_path / "user_plugins.json")
    # Third scope: dirs listed in BOUZECODE_PLUGIN_PATH are scanned too.
    monkeypatch.delenv(plugin_store.PLUGIN_PATH_ENV, raising=False)


@pytest.mark.backend
class TestPluginE2E:
    """Plugin system integration tests."""

    def test_plugin_list_empty(self, tmp_path, monkeypatch):
        """With no plugin installed in either scope, the loader returns nothing."""
        monkeypatch.chdir(tmp_path)

        from plugin.loader import load_all_plugins
        assert load_all_plugins() == []

    def test_plugin_register_tools_from_fake_plugin(self, tmp_path, monkeypatch):
        """A plugin installed in the USER store gets its tools into the registry.

        Nothing is stubbed out here: a real plugin directory is written, declared
        in the (isolated) user `plugins.json`, and discovered by the real
        `list_plugins()` → `register_plugin_tools()` path."""
        monkeypatch.chdir(tmp_path)

        plugin_dir = tmp_path / "fake-plugin"
        plugin_dir.mkdir()

        # The store reads plugin.json / PLUGIN.md — a manifest.yaml is ignored.
        (plugin_dir / "plugin.json").write_text(json.dumps({
            "name": "fake-plugin",
            "version": "1.0.0",
            "description": "A test plugin",
            "tools": ["fake_tools"],
        }), encoding="utf-8")

        # Create tools module
        tools_content = """\
from tool_registry import ToolDef

TOOL_DEFS = [
    ToolDef(
        name="FakePluginTool",
        schema={
            "name": "FakePluginTool",
            "description": "A fake tool from a plugin",
            "input_schema": {"type": "object", "properties": {"msg": {"type": "string"}}},
        },
        func=lambda p, c: f"Fake result: {p.get('msg', '')}",
        read_only=True,
        concurrent_safe=True,
    ),
]
"""
        (plugin_dir / "fake_tools.py").write_text(tools_content)

        # Declare it in the isolated user store, exactly as install_plugin would.
        import plugin.store as plugin_store
        plugin_store.USER_PLUGIN_CFG.write_text(json.dumps({"plugins": {
            "fake-plugin@user": {
                "name": "fake-plugin",
                "scope": "user",
                "source": str(plugin_dir),
                "install_dir": str(plugin_dir),
                "enabled": True,
            },
        }}), encoding="utf-8")

        # Register plugin tools
        from plugin.loader import register_plugin_tools
        count = register_plugin_tools()
        assert count >= 1

        # Verify tool is in registry
        from bouzecode.backend.core.tool_registry import get_tool
        tool = get_tool("FakePluginTool")
        assert tool is not None
        assert tool.name == "FakePluginTool"

        # Execute the tool
        result = tool.func({"msg": "hello"}, {})
        assert "Fake result: hello" in result

    def test_plugin_tool_used_by_llm(self, tmp_path, monkeypatch):
        """LLM invokes a plugin-registered tool through the engine."""
        monkeypatch.chdir(tmp_path)

        # Register a fake tool directly into the registry (simulating plugin load)
        from bouzecode.backend.core.tool_registry import register_tool, ToolDef, enable_tool

        register_tool(ToolDef(
            name="PluginGreet",
            schema={
                "name": "PluginGreet",
                "description": "Greet from plugin",
                "input_schema": {
                    "type": "object",
                    "properties": {"who": {"type": "string"}},
                },
            },
            func=lambda p, c: f"Hello {p.get('who', 'world')} from plugin!",
            read_only=True,
            concurrent_safe=True,
        ))
        enable_tool("PluginGreet")

        mock = MockLLM([
            '<tool_use name="PluginGreet" id="pg1"><param name="who">tester</param></tool_use>',
            "The plugin greeted the tester.",
        ])
        result = bouzecode(messages=["Use the plugin greet tool"], mock_llm=mock)

        assert mock.call_count == 2
        assert "greet" in result.last_reply.lower() or "plugin" in result.last_reply.lower()
