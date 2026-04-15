# [desc] Manages plugin lifecycle (install/uninstall/enable/disable/update) and config persistence. [/desc]
"""Plugin store: install/uninstall/enable/disable/update + config persistence."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .types import PluginEntry, PluginManifest, PluginScope, parse_plugin_identifier, sanitize_plugin_name

# ── Config paths ──────────────────────────────────────────────────────────────

USER_PLUGIN_DIR  = Path.home() / ".bouzecode" / "plugins"
USER_PLUGIN_CFG  = Path.home() / ".bouzecode" / "plugins.json"
PLUGIN_PATH_ENV  = "BOUZECODE_PLUGIN_PATH"

def _project_plugin_dir() -> Path:
    return Path.cwd() / ".bouzecode" / "plugins"

def _project_plugin_cfg() -> Path:
    return Path.cwd() / ".bouzecode" / "plugins.json"


# ── Config read/write ─────────────────────────────────────────────────────────

def _read_cfg(cfg_path: Path) -> dict:
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except Exception:
            pass
    return {"plugins": {}}


def _write_cfg(cfg_path: Path, data: dict) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, indent=2))


def _plugin_dir_for(scope: PluginScope) -> Path:
    return USER_PLUGIN_DIR if scope == PluginScope.USER else _project_plugin_dir()


def _plugin_cfg_for(scope: PluginScope) -> Path:
    return USER_PLUGIN_CFG if scope == PluginScope.USER else _project_plugin_cfg()


# ── External plugin dirs (from env var) ───────────────────────────────────────

def _external_plugin_dirs() -> list[Path]:
    """Read BOUZECODE_PLUGIN_PATH env var and return list of directories."""
    raw = os.environ.get(PLUGIN_PATH_ENV, "")
    if not raw:
        return []
    sep = ";" if os.name == "nt" else ":"
    return [Path(p.strip()) for p in raw.split(sep) if p.strip()]


def _scan_external_plugins() -> list[PluginEntry]:
    """Discover plugins from BOUZECODE_PLUGIN_PATH directories."""
    entries: list[PluginEntry] = []
    for base_dir in _external_plugin_dirs():
        if not base_dir.is_dir():
            continue
        # If base_dir itself is a plugin, use it directly
        manifest = PluginManifest.from_plugin_dir(base_dir)
        if manifest:
            entries.append(PluginEntry(
                name=manifest.name,
                scope=PluginScope.EXTERNAL,
                source=str(base_dir),
                install_dir=base_dir,
                enabled=True,
                manifest=manifest,
            ))
            continue
        # Otherwise scan subdirectories for plugins
        for sub in sorted(base_dir.iterdir()):
            if not sub.is_dir():
                continue
            manifest = PluginManifest.from_plugin_dir(sub)
            if manifest:
                entries.append(PluginEntry(
                    name=manifest.name,
                    scope=PluginScope.EXTERNAL,
                    source=str(sub),
                    install_dir=sub,
                    enabled=True,
                    manifest=manifest,
                ))
    return entries


# ── List ──────────────────────────────────────────────────────────────────────

def list_plugins(scope: PluginScope | None = None) -> list[PluginEntry]:
    """Return all installed plugins (optionally filtered by scope)."""
    entries: list[PluginEntry] = []
    managed_scopes = [s for s in (PluginScope.USER, PluginScope.PROJECT)
                      if scope is None or scope == s]
    for sc in managed_scopes:
        cfg = _read_cfg(_plugin_cfg_for(sc))
        for name, data in cfg.get("plugins", {}).items():
            entry = PluginEntry.from_dict(data)
            entry.manifest = PluginManifest.from_plugin_dir(entry.install_dir)
            entries.append(entry)
    if scope is None or scope == PluginScope.EXTERNAL:
        entries.extend(_scan_external_plugins())
    return entries


def get_plugin(name: str, scope: PluginScope | None = None) -> PluginEntry | None:
    for entry in list_plugins(scope):
        if entry.name == name:
            return entry
    return None


# ── Install ───────────────────────────────────────────────────────────────────

def install_plugin(
    identifier: str,
    scope: PluginScope = PluginScope.USER,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Install a plugin. identifier = 'name' | 'name@git_url' | 'name@local_path'.
    Returns (success, message).
    """
    name, source = parse_plugin_identifier(identifier)
    safe_name = sanitize_plugin_name(name)

    # Check if already installed
    existing = get_plugin(safe_name, scope)
    if existing and not force:
        return False, f"Plugin '{safe_name}' is already installed in {scope.value} scope. Use --force to reinstall."

    plugin_dir = _plugin_dir_for(scope) / safe_name

    try:
        if source is None:
            # No source → treat name as a local path if it exists, else error
            local = Path(name)
            if local.exists() and local.is_dir():
                source = str(local.resolve())
            else:
                return False, (
                    f"No source specified for '{name}'. "
                    "Provide 'name@git_url' or 'name@/local/path'."
                )

        # Install from local path or git
        if plugin_dir.exists() and force:
            shutil.rmtree(plugin_dir)

        if _is_git_url(source):
            ok, msg = _clone_plugin(source, plugin_dir)
            if not ok:
                return False, msg
        else:
            local_src = Path(source)
            if not local_src.exists():
                return False, f"Local path not found: {source}"
            shutil.copytree(str(local_src), str(plugin_dir))

        # Load and validate manifest
        manifest = PluginManifest.from_plugin_dir(plugin_dir)
        if manifest is None:
            manifest = PluginManifest(name=safe_name, description="(no manifest)")

        # Install pip dependencies
        if manifest.dependencies:
            dep_ok, dep_msg = install_dependencies(manifest.dependencies)
            if not dep_ok:
                return False, dep_msg

        # Persist to config
        entry = PluginEntry(
            name=safe_name,
            scope=scope,
            source=source,
            install_dir=plugin_dir,
            enabled=True,
            manifest=manifest,
        )
        _save_entry(entry)
        return True, f"Plugin '{safe_name}' installed successfully ({scope.value} scope)."

    except Exception as e:
        return False, f"Install failed: {e}"


def _is_git_url(source: str) -> bool:
    return (
        source.startswith("https://")
        or source.startswith("git@")
        or source.startswith("http://")
        or source.endswith(".git")
    )


def _clone_plugin(url: str, dest: Path) -> tuple[bool, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, f"git clone failed: {result.stderr.strip()}"
    return True, "cloned"


def _find_uv() -> str | None:
    """Find uv executable: shutil.which first, then known monorepo path."""
    found = shutil.which("uv")
    if found:
        return found
    known = Path(__file__).resolve().parents[2] / "uv.exe"
    if known.exists():
        return str(known)
    return None


def install_dependencies(deps: list[str]) -> tuple[bool, str]:
    uv = _find_uv()
    if uv:
        cmd = [uv, "pip", "install", "--quiet", "--python", sys.executable] + deps
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + deps
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        label = "uv pip install" if uv else "pip install"
        return False, f"{label} failed: {result.stderr.strip()}"
    return True, "deps installed"


def _save_entry(entry: PluginEntry) -> None:
    cfg_path = _plugin_cfg_for(entry.scope)
    data = _read_cfg(cfg_path)
    data.setdefault("plugins", {})[entry.name] = entry.to_dict()
    _write_cfg(cfg_path, data)


def _remove_entry(name: str, scope: PluginScope) -> None:
    cfg_path = _plugin_cfg_for(scope)
    data = _read_cfg(cfg_path)
    data.get("plugins", {}).pop(name, None)
    _write_cfg(cfg_path, data)


# ── Uninstall ─────────────────────────────────────────────────────────────────

def uninstall_plugin(
    name: str,
    scope: PluginScope | None = None,
    keep_data: bool = False,
) -> tuple[bool, str]:
    entry = get_plugin(name, scope)
    if entry is None:
        return False, f"Plugin '{name}' not found."
    if not keep_data and entry.install_dir.exists():
        shutil.rmtree(entry.install_dir)
    _remove_entry(entry.name, entry.scope)
    return True, f"Plugin '{name}' uninstalled."


# ── Enable / Disable ──────────────────────────────────────────────────────────

def _set_enabled(name: str, scope: PluginScope | None, enabled: bool) -> tuple[bool, str]:
    entry = get_plugin(name, scope)
    if entry is None:
        return False, f"Plugin '{name}' not found."
    entry.enabled = enabled
    _save_entry(entry)
    state = "enabled" if enabled else "disabled"
    return True, f"Plugin '{name}' {state}."


def enable_plugin(name: str, scope: PluginScope | None = None) -> tuple[bool, str]:
    return _set_enabled(name, scope, True)


def disable_plugin(name: str, scope: PluginScope | None = None) -> tuple[bool, str]:
    return _set_enabled(name, scope, False)


def disable_all_plugins(scope: PluginScope | None = None) -> tuple[bool, str]:
    entries = list_plugins(scope)
    if not entries:
        return True, "No plugins to disable."
    for entry in entries:
        entry.enabled = False
        _save_entry(entry)
    return True, f"Disabled {len(entries)} plugin(s)."


# ── Update ────────────────────────────────────────────────────────────────────

def update_plugin(name: str, scope: PluginScope | None = None) -> tuple[bool, str]:
    entry = get_plugin(name, scope)
    if entry is None:
        return False, f"Plugin '{name}' not found."
    if not _is_git_url(entry.source):
        return False, f"Plugin '{name}' was installed from a local path; cannot auto-update."
    if not entry.install_dir.exists():
        return False, f"Install directory missing: {entry.install_dir}"
    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(entry.install_dir),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, f"git pull failed: {result.stderr.strip()}"
    # Re-install dependencies if manifest changed
    manifest = PluginManifest.from_plugin_dir(entry.install_dir)
    if manifest and manifest.dependencies:
        install_dependencies(manifest.dependencies)
    return True, f"Plugin '{name}' updated. {result.stdout.strip()}"
