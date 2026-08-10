# [desc] Resolve a profile's required plugins at agent launch: install (pip/git/local) missing ones, enable them, return their tool names. [/desc]
"""Ensure an agent's `requires_plugins` are installed and enabled before launch.

Called from SubAgentManager._apply_profile. Each requirement is either a pip
name (str) or a dict ``{name, source}`` where ``source`` is a git URL, a local
dir, or omitted (pip / package index). Installs missing plugins (scope user), enables
them, and returns the tool names they contribute for the agent's allowed-tools.
"""
from __future__ import annotations

from ..plugin import (
    install_plugin, enable_plugin,
    register_plugin_tools, list_plugins,
)
from ..plugin.types import PluginScope


def _normalize(requirement) -> tuple[str, str | None]:
    """Return (package, source) from a str or {name/package, source} entry."""
    if isinstance(requirement, dict):
        name = requirement.get("name") or requirement.get("package") or ""
        return name, requirement.get("source")
    return str(requirement), None


def ensure_plugins(requirements: list) -> tuple[list[str], list[str]]:
    """Ensure each required plugin is installed+enabled. Idempotent.

    Returns (tool_names, errors). ``tool_names`` are the tool names newly
    available; ``errors`` are human-readable messages for plugins that could not
    be installed (e.g. package index or git unreachable) — surfaced, never swallowed.
    """
    tool_names: list[str] = []
    errors: list[str] = []

    for requirement in requirements:
        package, source = _normalize(requirement)
        if not package:
            errors.append(f"Entrée requires_plugins invalide: {requirement!r}")
            continue
        entry = _find_by_package(package)
        if entry is None:
            ok, msg = install_plugin(package, scope=PluginScope.USER, source=source)
            if not ok:
                errors.append(msg)
                continue
            entry = _find_by_package(package)
        if entry is None:
            errors.append(f"Plugin '{package}' installed but not registered.")
            continue
        if not entry.enabled:
            enable_plugin(entry.name)
        if entry.manifest:
            tool_names.extend(_tool_names_of(entry))

    # Register freshly enabled plugins' tools into the live registry.
    register_plugin_tools()
    return tool_names, errors


def _find_by_package(package: str):
    for entry in list_plugins():
        if entry.package == package or entry.name == package:
            return entry
    return None


def _tool_names_of(entry) -> list[str]:
    """Best-effort extraction of tool names from an enabled plugin."""
    from ..plugin.loader import _import_module, _tool_defs_from_module

    names: list[str] = []
    for module_name in entry.manifest.tools:
        mod = _import_module(entry, module_name)
        for tdef in _tool_defs_from_module(mod):
            names.append(tdef.name)
    return names
