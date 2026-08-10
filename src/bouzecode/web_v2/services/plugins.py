# [desc] Web service: list installed plugins and install a plugin (user scope, from the package index). [/desc]
"""Plugin management for the agent builder UI.

Thin wrapper over backend.plugin: list what's installed and install a package
(user scope) so the builder can offer plugins to attach to an agent.
"""
from __future__ import annotations

import importlib.metadata

from bouzecode.backend.plugin import (
    install_plugin,
    list_plugins,
    register_plugin_tools,
)
from bouzecode.backend.plugin.store import _is_git_source
from bouzecode.backend.plugin.types import PluginScope
from bouzecode.backend.commands.agent_upgrade import _plugins_to_upgrade
from bouzecode.backend.profiles.discovery import load_user_profiles


def _pkg_version(package: str) -> str | None:
    """Best-effort installed version of a distribution, None if absent."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def list_installed() -> list[dict]:
    """Installed plugins with the tool names they contribute."""
    out: list[dict] = []
    for entry in list_plugins():
        manifest = entry.manifest
        out.append({
            "name": entry.name,
            "package": entry.package,
            "scope": entry.scope.value,
            "enabled": entry.enabled,
            "description": manifest.description if manifest else "",
            "tools": list(manifest.tools) if manifest else [],
            "version": _pkg_version(entry.package),
            "source": getattr(entry, "source", None),
        })
    return out


def upgrade_profile_plugins(agent_name: str | None, confirm_git: bool = False) -> dict:
    """Upgrade the plugins required by one agent (or all profiles).

    Returns one of:
      - {"error": <msg>} when the agent name is unknown;
      - {"requires_confirmation": True, "sources": [...git urls...], "message": ...}
        when a git source is involved and confirm_git is False;
      - {"results": [{package, ok, before, after, message}, ...]} otherwise.
    """
    profiles = load_user_profiles()
    entries, error = _plugins_to_upgrade(profiles, agent_name)
    if error:
        return {"error": error}

    git_sources = [
        e["source"]
        for e in entries
        if e.get("source") and _is_git_source(e["source"])
    ]
    if git_sources and not confirm_git:
        return {
            "requires_confirmation": True,
            "sources": git_sources,
            "message": (
                "Cette mise a jour clonera et executera du code depuis: "
                + ", ".join(git_sources)
                + ". Confirme pour continuer."
            ),
        }

    results: list[dict] = []
    for entry in entries:
        package = entry["package"]
        source = entry.get("source")
        before = _pkg_version(package)
        ok, msg = install_plugin(package, scope=PluginScope.USER, source=source)
        after = _pkg_version(package)
        results.append({
            "package": package,
            "ok": ok,
            "before": before,
            "after": after,
            "message": msg,
        })
    register_plugin_tools()
    return {"results": results}


def install(package: str, source: str | None = None, confirm_git: bool = False) -> dict | str:
    """Install a plugin at user scope. Returns info dict or error string.

    ``source`` may be a git URL (cloned + installed), a local directory, or
    omitted (pip name resolved from the configured package index). For a git/local source the
    ``package`` (pip distribution name) is still required as the registry key.

    Installing from a git source runs code fetched from that URL, so it requires
    an explicit ``confirm_git``. Without it, returns a ``requires_confirmation``
    payload the UI must surface before retrying with confirm_git=True.
    """
    package = (package or "").strip()
    source = (source or "").strip() or None
    if not package:
        return "package requis"
    if source and _is_git_source(source) and not confirm_git:
        return {
            "requires_confirmation": True,
            "source": source,
            "message": (
                f"Installer '{package}' clonera et exécutera du code depuis {source}. "
                "Confirme pour continuer."
            ),
        }
    ok, msg = install_plugin(package, scope=PluginScope.USER, source=source)
    if not ok:
        return msg
    return {"ok": True, "message": msg}


def from_gitlab(raw_input: str, confirm_git: bool = False) -> dict | str:
    """Install a plugin from a GitLab repo URL or a local git folder path.

    One repo == one pip package: we derive the distribution name and try
    the private package index first; if it's not published there, we fall back to installing
    from the repo's git source (clone + run fetched code), which requires an
    explicit ``confirm_git``. Returns an info dict, a ``requires_confirmation``
    payload, or an error string.
    """
    from bouzecode.backend.core.gitlab_resolve import (
        SourceError, plugin_install_target, resolve_input,
    )
    try:
        info = resolve_input(raw_input)
    except SourceError as exc:
        return str(exc)
    package, git_source = plugin_install_target(info)

    ok, msg = install_plugin(package, scope=PluginScope.USER, source=None)  # package index
    if ok:
        return {"ok": True, "message": msg, "package": package, "via": "index"}
    if not confirm_git:
        return {
            "requires_confirmation": True, "package": package, "source": git_source,
            "message": (
                f"'{package}' introuvable sur l'index de paquets. Installer depuis le repo git "
                f"{info['web_url']} (clone + exécution de code) ?"
            ),
        }
    # git fallback = plain `git clone` (ambient git creds, no token injection).
    ok, msg = install_plugin(package, scope=PluginScope.USER, source=git_source)
    if not ok:
        return (
            f"Échec du clone de {info['web_url']} : {msg}. Vérifie ta connexion au "
            "GitLab et ton accès au repo (git doit pouvoir cloner), ou publie le "
            "plugin sur l'index de paquets pour l'installer par nom."
        )
    return {"ok": True, "message": msg, "package": package, "via": "git"}
