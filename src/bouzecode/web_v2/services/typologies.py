# [desc] Builds agent typologies from real YAML profiles + builtin system agents as single source of truth. [/desc]
"""Build agent typologies from real profiles and the builtin system agents."""
from __future__ import annotations

from bouzecode.paths import project_dir as bouzecode_project_dir
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


def _typologie(name: str, description: str, profile) -> dict[str, Any]:
    return {"name": name, "description": description, "profile": name,
            "default_model": getattr(profile, "model", "") or "", "default_cwd": ""}


def _profils_yaml(project_path: str | None):
    """(nom, profil) des profils YAML éditables : projet, global, puis dossiers extra.
    Les agents autonomes d'application (`kind: app`, ex. `focus`) ne sont pas dispatchables."""
    from bouzecode.backend.core.paths import get_extra_dirs
    from bouzecode.web_v2.services.profiles import load_profiles_from_dir, user_global_dir

    directories = [bouzecode_project_dir(Path(project_path)) / "profiles"] if project_path else []
    directories += [user_global_dir(), *(d / "profiles" for d in get_extra_dirs())]
    for directory in directories:
        for name, profile in load_profiles_from_dir(directory).items():
            if getattr(profile, "kind", "user") != "app":
                yield name, profile


def list_typologies(project_path: str | None = None) -> list[dict[str, Any]]:
    """Typologies = profils YAML + agents système intégrés (source unique).

    'default' toujours en premier ; au premier nom rencontré de gagner (un profil utilisateur
    masque l'agent système homonyme)."""
    from bouzecode.backend.profiles.discovery import load_system_profiles

    result: dict[str, dict[str, Any]] = {"default": dict(_DEFAULT_TYPOLOGY)}
    for name, profile in _profils_yaml(project_path):
        description = (getattr(profile, "system_prompt_extra", "") or "")[:80] or f"Profil {name}"
        result.setdefault(name, _typologie(name, description, profile))
    for name, profile in load_system_profiles().items():
        description = getattr(profile, "description", "") or f"Agent {name}"
        result.setdefault(name, _typologie(name, description, profile))
    return list(result.values())


def get_typology(name: str, project_path: str | None = None) -> dict[str, Any] | None:
    """Find a single typology by name. Returns None if not found."""
    for t in list_typologies(project_path):
        if t["name"] == name:
            return t
    return None
