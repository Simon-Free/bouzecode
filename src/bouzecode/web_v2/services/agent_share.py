# [desc] Export/import a shareable agent profile (YAML + requires_plugins); import installs missing plugins. [/desc]
"""Share an agent as a file.

Export → the profile's YAML text (with requires_plugins).
Import → write it into ~/.bouzecode/profiles and install any declared plugins
(user scope, from the private package index) so the agent works for the recipient —
provided they can reach that index.
"""
from __future__ import annotations

import yaml

from bouzecode.backend.plugin.store import _is_git_source
from . import profiles as profiles_svc


def export_agent(name: str) -> str | None:
    """Return the YAML text for a global profile, or None if unknown."""
    profile = profiles_svc.get_profile(name)
    if profile is None:
        return None
    return yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)


def _git_sources(requirements: list) -> list[str]:
    """Git sources among the requirements (these execute fetched code)."""
    out: list[str] = []
    for req in requirements:
        if isinstance(req, dict):
            src = str(req.get("source") or "").strip()
            if src and _is_git_source(src):
                out.append(src)
    return out


def import_agent(yaml_text: str, confirm_git: bool = False) -> dict | str:
    """Save an exported agent and install its required plugins.

    If the agent requires plugins from git sources (which execute fetched code),
    a confirmation is required first: without ``confirm_git`` the agent is NOT
    saved and a ``requires_confirmation`` payload is returned listing the sources.
    Returns {"name", "installed", "errors"} on success, or an error string.
    """
    try:
        data = yaml.safe_load(yaml_text or "")
    except yaml.YAMLError as error:
        return f"YAML d'agent illisible : {error}"
    if not isinstance(data, dict) or not data.get("name"):
        return "YAML d'agent invalide : champ 'name' requis"

    git_sources = _git_sources(data.get("requires_plugins") or [])
    if git_sources and not confirm_git:
        return {
            "requires_confirmation": True,
            "git_sources": git_sources,
            "message": (
                f"Cet agent installe {len(git_sources)} plugin(s) depuis des sources git "
                "(clone + exécution de code). Confirme pour importer."
            ),
        }

    saved = profiles_svc.save_profile(data)
    if isinstance(saved, str):
        return saved

    installed, errors = _install_required(saved.get("requires_plugins") or [])
    return {"name": saved["name"], "installed": installed, "errors": errors}


def _install_required(packages: list) -> tuple[list[str], list[str]]:
    from bouzecode.backend.multi_agent.plugin_resolver import ensure_plugins
    tool_names, errors = ensure_plugins(packages)
    return tool_names, errors
