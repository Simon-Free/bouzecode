# [desc] Plugin loader: import enabled plugins' tool modules and register their TOOL_DEFS / skill paths. [/desc]
"""Plugin loader: discover and register tools/skills from enabled plugins."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .store import list_plugins
from .types import PluginEntry, PluginScope


def _enabled(scope: PluginScope | None) -> list[PluginEntry]:
    return [p for p in list_plugins(scope) if p.enabled]


def _import_module(entry: PluginEntry, module_name: str):
    """Import a plugin's tool module.

    ``module_name`` may name a submodule (``"tools"`` → ``pkg.tools``) or the
    package itself (the package name, or empty) when ``TOOLS`` lives in
    ``__init__.py``.
    """
    root_str = str(entry.import_root.parent)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    pkg = entry.import_root.name
    if not module_name or module_name == pkg:
        return importlib.import_module(pkg)
    return importlib.import_module(f"{pkg}.{module_name}")


def _tool_defs_from_module(mod) -> list:
    """Build ToolDef objects from a plugin module.

    Plugins expose ``TOOLS`` = list of pure dicts (no bouzecode import) and
    bouzecode constructs the ToolDef here — so plugins never depend on bouzecode.
    A legacy ``TOOL_DEFS`` (pre-built ToolDef list) is accepted as a fallback.
    """
    from bouzecode.backend.core.tool_registry import ToolDef

    if hasattr(mod, "TOOLS"):
        defs = []
        for spec in mod.TOOLS:
            defs.append(ToolDef(
                name=spec["name"],
                schema={
                    "name": spec["name"],
                    "description": spec["description"],
                    "input_schema": spec["input_schema"],
                },
                func=spec["func"],
                read_only=spec.get("read_only", False),
                concurrent_safe=spec.get("concurrent_safe", False),
                ends_turn=spec.get("ends_turn", False),
            ))
        return defs
    return list(getattr(mod, "TOOL_DEFS", []))


def register_plugin_tools(scope: PluginScope | None = None) -> int:
    """Register every tool exported by enabled plugins. Returns the count."""
    from bouzecode.backend.core.tool_registry import register_tool

    count = 0
    for entry in _enabled(scope):
        if not entry.manifest:
            continue
        for module_name in entry.manifest.tools:
            mod = _import_module(entry, module_name)
            for tdef in _tool_defs_from_module(mod):
                register_tool(tdef)
                count += 1
    return count


def _hook_defs_from_module(mod) -> list:
    """Return the HookDef objects a plugin hook module exports (mirror of
    _tool_defs_from_module). Plugins build HookDef directly from the pipeline
    types — same contract as a builtin hook module."""
    return list(getattr(mod, "HOOK_DEFS", []))


def register_plugin_hooks(scope: PluginScope | None = None) -> int:
    """Register every hook exported by enabled plugins into the named-hook
    catalog. A profile can then reference a plugin hook by name in `hooks: [...]`,
    exactly like a builtin. Returns the count."""
    from bouzecode.backend.agent.hooks.pipeline import register_named_hook

    count = 0
    for entry in _enabled(scope):
        if not entry.manifest:
            continue
        for module_name in entry.manifest.hooks:
            mod = _import_module(entry, module_name)
            for hdef in _hook_defs_from_module(mod):
                register_named_hook(hdef)
                count += 1
    return count


def load_plugin_skills(scope: PluginScope | None = None) -> list[Path]:
    """Return skill .md paths contributed by enabled plugins."""
    paths: list[Path] = []
    for entry in _enabled(scope):
        if not entry.manifest:
            continue
        for skill_rel in entry.manifest.skills:
            skill_path = entry.import_root / skill_rel
            if skill_path.exists():
                paths.append(skill_path)
    return paths
