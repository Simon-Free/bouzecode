# [desc] Plugin store: install via pip, register in plugins.json, enable/disable/list. [/desc]
"""Plugin store: install/list/enable/disable + plugins.json persistence.

Plugins are pip packages. ``install_plugin`` runs ``pip install <package>``
(resolving from the ambient package index), then locates the installed
package's import root to read its shipped ``plugin.json`` and records an entry in
the scope's ``plugins.json``.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from bouzecode.backend.core import config
from .types import PluginEntry, PluginManifest, PluginScope, sanitize_plugin_name


def _cfg_path(scope: PluginScope) -> Path:
    # Read config.CONFIG_DIR dynamically (not a captured value) so tests that
    # monkeypatch it, and any runtime override, are honoured.
    base = config.CONFIG_DIR if scope == PluginScope.USER else Path.cwd() / ".bouzecode"
    return base / "plugins.json"


def _read_cfg(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"plugins": {}}


def _write_cfg(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── List / get ───────────────────────────────────────────────────────────────

def list_plugins(scope: PluginScope | None = None) -> list[PluginEntry]:
    """Return installed plugins (optionally filtered by scope)."""
    entries: list[PluginEntry] = []
    scopes = [PluginScope.USER, PluginScope.PROJECT] if scope is None else [scope]
    for sc in scopes:
        cfg = _read_cfg(_cfg_path(sc))
        for data in cfg.get("plugins", {}).values():
            entry = PluginEntry.from_dict(data)
            entry.manifest = PluginManifest.from_import_root(entry.import_root)
            entries.append(entry)
    return entries


def get_plugin(name: str, scope: PluginScope | None = None) -> PluginEntry | None:
    for entry in list_plugins(scope):
        if entry.name == name:
            return entry
    return None


# ── Install ──────────────────────────────────────────────────────────────────

def _pip_install(package: str, index_url: str | None) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", package]
    if index_url:
        cmd += ["--index-url", index_url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"pip install {package} failed: {result.stderr.strip()}"
    return True, "installed"


def _is_git_source(source: str) -> bool:
    return (
        source.startswith(("git+", "git@", "https://", "http://", "ssh://"))
        or source.endswith(".git")
    )


def _pip_install_path(path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, f"pip install {path} failed: {result.stderr.strip()}"
    return True, "installed"


def _clone_and_install(source: str) -> tuple[bool, str]:
    """git clone a plugin repo into the plugins cache, then pip install it."""
    url = source[4:] if source.startswith("git+") else source
    dest = config.CONFIG_DIR / "plugin_src" / sanitize_plugin_name(url.rsplit("/", 1)[-1].removesuffix(".git"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        pull = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"],
                              capture_output=True, text=True)
        if pull.returncode != 0:
            return False, f"git pull failed for {dest}: {pull.stderr.strip()}"
    else:
        clone = subprocess.run(["git", "clone", "--depth", "1", url, str(dest)],
                               capture_output=True, text=True)
        if clone.returncode != 0:
            return False, f"git clone failed: {clone.stderr.strip()}"
    return _pip_install_path(dest)


def _top_level_modules(package: str) -> list[str]:
    """Top-level import names a distribution provides (from its metadata).

    The pip distribution name (``my-sql-plugin``) is often not the import
    name (``my_sql``), so we read the installed distribution's record of
    top-level packages rather than guessing from the dist name.
    """
    import importlib.metadata as md

    try:
        dist = md.distribution(package)
    except md.PackageNotFoundError:
        return []
    names: list[str] = []
    top_level = dist.read_text("top_level.txt")
    if top_level:
        names += [line.strip() for line in top_level.splitlines() if line.strip()]
    # Fallback: infer top-level packages from the RECORD of installed files.
    for f in dist.files or []:
        parts = f.parts
        if len(parts) >= 2 and parts[0].isidentifier() and parts[1] == "__init__.py":
            if parts[0] not in names:
                names.append(parts[0])
    return names


def _import_root_of(package: str) -> Path | None:
    """Resolve the on-disk import root of an installed plugin package.

    Tries the distribution's declared top-level modules first, then falls back
    to the dist-name-with-underscores heuristic.
    """
    # A freshly pip-installed package is invisible to a long-running process
    # until the import-system caches are refreshed.
    importlib.invalidate_caches()
    candidates = _top_level_modules(package) or [package.replace("-", "_")]
    roots: list[Path] = []
    for module_name in candidates:
        spec = importlib.util.find_spec(module_name)
        if spec is not None and spec.origin:
            roots.append(Path(spec.origin).parent)
    # A plugin may ship several top-level packages (e.g. a vendored lib + the
    # tool package); the import root is the one carrying plugin.json.
    for root in roots:
        if (root / "plugin.json").exists():
            return root
    return roots[0] if roots else None


def install_plugin(
    package: str,
    scope: PluginScope = PluginScope.USER,
    index_url: str | None = None,
    source: str | None = None,
) -> tuple[bool, str]:
    """Install a plugin and register it from its shipped plugin.json.

    ``package`` is the pip distribution name (also the registry key). ``source``
    selects where to install from:
      - None / pip name  → pip install <package> (via the ambient package index)
      - git URL / git+…  → git clone into the plugins cache, then pip install it
      - local directory  → pip install <dir>
    A plugin's own ``dependencies`` are pulled by pip → self-contained.
    """
    if source and _is_git_source(source):
        ok, msg = _clone_and_install(source)
    elif source and Path(source).is_dir():
        ok, msg = _pip_install_path(Path(source))
    else:
        ok, msg = _pip_install(package, index_url)
    if not ok:
        return False, msg

    import_root = _import_root_of(package)
    if import_root is None:
        return False, f"Installed '{package}' but could not locate its import root."

    manifest = PluginManifest.from_import_root(import_root)
    if manifest is None:
        return False, f"Package '{package}' ships no plugin.json at {import_root}."

    entry = PluginEntry(
        name=sanitize_plugin_name(manifest.name),
        scope=scope,
        package=package,
        import_root=import_root,
        enabled=True,
        manifest=manifest,
    )
    _save_entry(entry)
    return True, f"Plugin '{entry.name}' installed ({scope.value} scope)."


def _save_entry(entry: PluginEntry) -> None:
    path = _cfg_path(entry.scope)
    data = _read_cfg(path)
    data.setdefault("plugins", {})[entry.name] = entry.to_dict()
    _write_cfg(path, data)


# ── Enable / disable ─────────────────────────────────────────────────────────

def _set_enabled(name: str, scope: PluginScope | None, enabled: bool) -> tuple[bool, str]:
    entry = get_plugin(name, scope)
    if entry is None:
        return False, f"Plugin '{name}' not found."
    entry.enabled = enabled
    _save_entry(entry)
    return True, f"Plugin '{name}' {'enabled' if enabled else 'disabled'}."


def enable_plugin(name: str, scope: PluginScope | None = None) -> tuple[bool, str]:
    return _set_enabled(name, scope, True)


def disable_plugin(name: str, scope: PluginScope | None = None) -> tuple[bool, str]:
    return _set_enabled(name, scope, False)
