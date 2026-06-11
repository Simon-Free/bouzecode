# [desc] Loads and parses agent profile YAML files into AgentProfile dataclass instances. [/desc]
from __future__ import annotations

from pathlib import Path
from typing import Dict

import yaml

from bouzecode.backend.profiles.models import AgentProfile


def load_profile_from_path(path: Path) -> AgentProfile:
    """Parse a single YAML profile file into an AgentProfile."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AgentProfile(
        name=str(data.get("name", path.stem)),
        skills=_as_str_list(data.get("skills", [])),
        tools=_as_str_list(data.get("tools", [])),
        hooks=_as_str_list(data.get("hooks", [])),
        model=str(data.get("model", "") or ""),
        system_prompt_extra=str(data.get("system_prompt_extra", "") or ""),
    )


def load_profiles_from_dir(directory: Path) -> Dict[str, AgentProfile]:
    """Load all *.yaml and *.yml profiles from a directory."""
    profiles: Dict[str, AgentProfile] = {}
    if not directory.is_dir():
        return profiles
    for ext in ("*.yaml", "*.yml"):
        for p in sorted(directory.glob(ext)):
            profile = load_profile_from_path(p)
            profiles[profile.name] = profile
    return profiles


def _as_str_list(value) -> list[str]:
    """Normalize a value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []
