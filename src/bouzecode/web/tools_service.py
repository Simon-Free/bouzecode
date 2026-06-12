# [desc] Loads builtin and plugin tools, then exposes a sorted list of ToolView summaries. [/desc]
"""List all registered tools (builtins + plugins) with their descriptions."""
from __future__ import annotations

from dataclasses import dataclass

from bouzecode.backend import tools  # noqa: F401  triggers _register_builtins()
# REMOVED: from bouzecode.backend.plugin.loader import register_plugin_tools  # module deleted
from bouzecode.backend.core.tool_registry import get_all_tools


_plugins_loaded = False


def _ensure_plugins_loaded() -> None:
    # plugin.loader was removed; builtins register on import of bouzecode.backend.tools.
    global _plugins_loaded
    _plugins_loaded = True


@dataclass
class ToolView:
    name: str
    description: str
    read_only: bool
    concurrent_safe: bool


def list_tool_views() -> list[ToolView]:
    _ensure_plugins_loaded()
    views = [
        ToolView(
            name=tool_def.name,
            description=tool_def.schema.get("description", ""),
            read_only=tool_def.read_only,
            concurrent_safe=tool_def.concurrent_safe,
        )
        for tool_def in get_all_tools()
    ]
    views.sort(key=lambda view: view.name.lower())
    return views
