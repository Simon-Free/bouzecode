# [desc] Discovers, imports, and registers tools, skills, and MCP configs from enabled plugins. [/desc]
"""Plugin loader: discover and load tools/skills/mcp from installed plugins."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .store import list_plugins, install_dependencies
from .types import PluginEntry, PluginScope


def load_all_plugins(scope: PluginScope | None = None) -> list[PluginEntry]:
    """Return enabled plugins (optionally filtered by scope)."""
    return [p for p in list_plugins(scope) if p.enabled]


# ── Dependency checking ──────────────────────────────────────────────────────

def _strip_version_spec(dep: str) -> str:
    """Extract bare package name from a pip spec like 'polars>=0.20.1'."""
    for ch in "><=!;[":
        idx = dep.find(ch)
        if idx != -1:
            dep = dep[:idx]
    return dep.strip()


def check_missing_deps(deps: list[str]) -> list[str]:
    """Return dependency specs whose packages are not currently installed."""
    from importlib.metadata import distribution, PackageNotFoundError
    missing = []
    for dep in deps:
        pkg_name = _strip_version_spec(dep)
        try:
            distribution(pkg_name)
        except PackageNotFoundError:
            missing.append(dep)
    return missing


def ensure_plugin_dependencies(entry: PluginEntry) -> tuple[bool, str]:
    """Check and auto-install missing pip dependencies for a plugin."""
    if not entry.manifest or not entry.manifest.dependencies:
        return True, ""
    missing = check_missing_deps(entry.manifest.dependencies)
    if not missing:
        return True, ""
    print(f"[plugin] Installing missing dependencies for '{entry.name}': {', '.join(missing)}")
    return install_dependencies(missing)


# ── Tool loading ─────────────────────────────────────────────────────────────

def load_plugin_tools(scope: PluginScope | None = None) -> list[dict]:
    """
    Import tool modules from all enabled plugins and collect their TOOL_SCHEMAS.
    Returns combined list of tool schema dicts.
    """
    schemas: list[dict] = []
    for entry in load_all_plugins(scope):
        if not entry.manifest or not entry.manifest.tools:
            continue
        ok, msg = ensure_plugin_dependencies(entry)
        if not ok:
            print(f"[plugin] Skipping '{entry.name}': {msg}")
            continue
        for module_name in entry.manifest.tools:
            mod = _import_plugin_module(entry, module_name)
            if mod and hasattr(mod, "TOOL_SCHEMAS"):
                schemas.extend(mod.TOOL_SCHEMAS)
    return schemas


def register_plugin_tools(scope: PluginScope | None = None) -> int:
    """
    Import tool modules from enabled plugins and register them into tool_registry.
    Returns number of tools registered.
    """
    from tool_registry import register_tool, ToolDef
    count = 0
    for entry in load_all_plugins(scope):
        if not entry.manifest or not entry.manifest.tools:
            continue
        ok, msg = ensure_plugin_dependencies(entry)
        if not ok:
            print(f"[plugin] Skipping '{entry.name}': {msg}")
            continue
        for module_name in entry.manifest.tools:
            mod = _import_plugin_module(entry, module_name)
            if mod is None:
                continue
            # Register each ToolDef exported by the module
            if hasattr(mod, "TOOL_DEFS"):
                for tdef in mod.TOOL_DEFS:
                    register_tool(tdef)
                    count += 1
    return count


def load_plugin_skills(scope: PluginScope | None = None) -> list[Path]:
    """Return paths to skill markdown files from enabled plugins."""
    paths: list[Path] = []
    for entry in load_all_plugins(scope):
        if not entry.manifest or not entry.manifest.skills:
            continue
        for skill_rel in entry.manifest.skills:
            skill_path = entry.install_dir / skill_rel
            if skill_path.exists():
                paths.append(skill_path)
    return paths


def load_plugin_mcp_configs(scope: PluginScope | None = None) -> dict:
    """Return mcp server configs contributed by enabled plugins."""
    configs: dict = {}
    for entry in load_all_plugins(scope):
        if not entry.manifest or not entry.manifest.mcp_servers:
            continue
        for server_name, server_cfg in entry.manifest.mcp_servers.items():
            # Prefix server name with plugin name to avoid collisions
            qualified = f"{entry.name}__{server_name}"
            configs[qualified] = server_cfg
    return configs


def _import_plugin_module(entry: PluginEntry, module_name: str):
    """Dynamically import a module from a plugin directory."""
    plugin_dir_str = str(entry.install_dir)
    if plugin_dir_str not in sys.path:
        sys.path.insert(0, plugin_dir_str)

    unique_name = f"_plugin_{entry.name}_{module_name}"
    if unique_name in sys.modules:
        return sys.modules[unique_name]

    candidates = [
        entry.install_dir / f"{module_name}.py",
        entry.install_dir / module_name / "__init__.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            spec = importlib.util.spec_from_file_location(unique_name, candidate)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[unique_name] = mod
                try:
                    spec.loader.exec_module(mod)
                    return mod
                except ModuleNotFoundError as e:
                    del sys.modules[unique_name]
                    return _retry_after_install(entry, module_name, e, spec, unique_name)
                except Exception as e:
                    print(f"[plugin] Failed to load {module_name} from {entry.name}: {e}")
                    del sys.modules[unique_name]
    return None


def _retry_after_install(entry, module_name, error, spec, unique_name):
    """Auto-install a missing dependency and retry the plugin module import."""
    missing_pkg = error.name
    if not missing_pkg:
        print(f"[plugin] Failed to load {module_name} from {entry.name}: {error}")
        return None
    print(f"[plugin] Auto-installing '{missing_pkg}' for plugin '{entry.name}'...")
    ok, msg = install_dependencies([missing_pkg])
    if not ok:
        print(f"[plugin] Could not install '{missing_pkg}': {msg}")
        return None
    importlib.invalidate_caches()
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception as e2:
        print(f"[plugin] Failed to load {module_name} from {entry.name} after install: {e2}")
        del sys.modules[unique_name]
        return None
