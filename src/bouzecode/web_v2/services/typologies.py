# [desc] Builds agent typologies from real YAML profiles + builtin system agents as single source of truth. [/desc]
"""Build agent typologies from real profiles and the builtin system agents."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TYPOLOGY: dict[str, Any] = {
    "name": "default",
    "description": "Agent standard",
    "profile": "",
    "default_model": "",
    "default_cwd": "",
}


def list_typologies(project_path: str | None = None) -> list[dict[str, Any]]:
    """Return typologies built from real profiles + agent definitions (single source of truth).

    The 'default' typology is always first.
    """
    from bouzecode.backend.core.paths import get_extra_dirs
    from bouzecode.backend.profiles.discovery import load_system_profiles
    from bouzecode.web_v2.services.profiles import load_profiles_from_dir, user_global_dir

    seen: set[str] = {"default"}
    result: list[dict[str, Any]] = [dict(_DEFAULT_TYPOLOGY)]

    # 1) Profiles YAML (project-local, global, extra dirs) — these are the user-editable ones
    sources: list[tuple[str, Path]] = []
    if project_path:
        sources.append(("projet", Path(project_path) / ".bouzecode" / "profiles"))
    sources.append(("global", user_global_dir()))
    sources += [("extra", d / "profiles") for d in get_extra_dirs()]

    for _label, directory in sources:
        for name, profile in load_profiles_from_dir(directory).items():
            if name in seen:
                continue
            # Standalone host-app agents (kind: app, e.g. `focus`) route directly via their
            # host, never via the manager — they must not be a dispatchable typology.
            if getattr(profile, "kind", "user") == "app":
                continue
            seen.add(name)
            result.append({
                "name": name,
                "description": (getattr(profile, "system_prompt_extra", "") or "")[:80] or f"Profil {name}",
                "profile": name,
                "default_model": getattr(profile, "model", "") or "",
                "default_cwd": "",
            })

    # 2) Built-in system agents (general-purpose / meta-agent / manager), unless a
    #    same-named user profile already shadows them.
    for name, profile in load_system_profiles().items():
        if name in seen:
            continue
        seen.add(name)
        result.append({
            "name": name,
            "description": (getattr(profile, "description", "") or "") or f"Agent {name}",
            "profile": name,
            "default_model": getattr(profile, "model", "") or "",
            "default_cwd": "",
        })

    return result


def get_typology(name: str, project_path: str | None = None) -> dict[str, Any] | None:
    """Find a single typology by name. Returns None if not found."""
    for t in list_typologies(project_path):
        if t["name"] == name:
            return t
    return None
