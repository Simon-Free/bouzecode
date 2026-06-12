# [desc] Load and query agent typologies from .bouzecode/web_typologies.yaml config files. [/desc]
"""Load and query agent typologies from .bouzecode/web_typologies.yaml."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_TYPOLOGY: dict[str, Any] = {
    "name": "default",
    "description": "Agent standard",
    "profile": "",
    "default_model": "",
    "default_cwd": "",
}

_GLOBAL_FILE = Path.home() / ".bouzecode" / "web_typologies.yaml"


def _load_file(path: Path) -> list[dict[str, Any]]:
    """Load typologies from a single YAML file. Returns [] on any error."""
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = data.get("typologies", [])
        if not isinstance(raw, list):
            return []
        result = []
        for entry in raw:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            result.append({
                "name": entry["name"],
                "description": entry.get("description", ""),
                "profile": entry.get("profile", ""),
                "default_model": entry.get("default_model", ""),
                "default_cwd": entry.get("default_cwd", ""),
            })
        return result
    except Exception as exc:
        logger.warning("typologies: failed to load %s: %s", path, exc)
        return []


def list_typologies(project_path: str | None = None) -> list[dict[str, Any]]:
    """Return typologies (project-local merged with global, deduplicated by name).

    The 'default' typology is always first.
    """
    seen: set[str] = {"default"}
    result: list[dict[str, Any]] = [dict(_DEFAULT_TYPOLOGY)]

    # Project-local takes priority
    if project_path:
        project_file = Path(project_path) / ".bouzecode" / "web_typologies.yaml"
        for t in _load_file(project_file):
            if t["name"] not in seen:
                seen.add(t["name"])
                result.append(t)

    # Then global
    for t in _load_file(_GLOBAL_FILE):
        if t["name"] not in seen:
            seen.add(t["name"])
            result.append(t)

    return result


def get_typology(name: str, project_path: str | None = None) -> dict[str, Any] | None:
    """Find a single typology by name. Returns None if not found."""
    for t in list_typologies(project_path):
        if t["name"] == name:
            return t
    return None
