"""E2E test: Plugin system — list plugins, load a fake plugin with tools."""
from __future__ import annotations

import pytest
from pathlib import Path

from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


@pytest.mark.backend
class TestPluginE2E:
    """Plugin system integration tests."""

    def test_plugin_list_empty(self, tmp_path, monkeypatch):
        """When no plugins installed, /plugin list returns empty."""
        monkeypatch.chdir(tmp_path)
        # Monkeypatch plugin store to return empty
        import plugin.store as plugin_store
        monkeypatch.setattr(plugin_store, "list_plugins", lambda scope=None: [])

        mock = MockLLM([
            "No plugins are installed.",
        ])
        # Use the /plugin slash command via the harness isn't direct —
        # test plugin tool registration instead
        from plugin.loader import load_all_plugins
        plugins = load_all_plugins()
        assert plugins == []

    def test_plugin_register_tools_from_fake_plugin(self, tmp_path, monkeypatch):
        """Create a minimal plugin structure and register its tools."""
        monkeypatch.chdir(tmp_path)

        # Create a fake plugin directory structure
        plugin_dir = tmp_path / "fake-plugin"
        plugin_dir.mkdir()

        # Create manifest
        manifest_content = """\
name: fake-plugin
version: 1.0.0
description: A test plugin
tools:
  - fake_tools
"""
        (plugin_dir / "manifest.yaml").write_text(manifest_content)

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

        # Mock plugin store to return our fake plugin
        from plugin.types import PluginEntry, PluginManifest, PluginScope
        fake_manifest = PluginManifest(
            name="fake-plugin",
            version="1.0.0",
            description="A test plugin",
            tools=["fake_tools"],
        )
        fake_entry = PluginEntry(
            name="fake-plugin",
            path=str(plugin_dir),
            scope=PluginScope.USER,
            enabled=True,
            manifest=fake_manifest,
        )

        import plugin.store as plugin_store
        monkeypatch.setattr(plugin_store, "list_plugins", lambda scope=None: [fake_entry])
        monkeypatch.setattr(plugin_store, "install_dependencies", lambda e: (True, "ok"))

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
