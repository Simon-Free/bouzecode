# [desc] Serialization + input-sanitizing helpers for the agent-builder profile service. [/desc]
"""Shared helpers for the profiles service: hook catalogue, name validation,
profile serialization, and request-payload cleaning (tools/hooks/plugins)."""
from __future__ import annotations

import re

# Hooks bouzecode actually wires (see SubAgentManager._HOOK_FLAGS).
HOOKS = [
    {"name": "test_enforcement",
     "description": "Exige l'appel de RunPythonTest (TDD) avant de pouvoir clôturer."},
    {"name": "enforcement",
     "description": "Exige Methodology/Snippet à chaque tour."},
    {"name": "loop_detection",
     "description": "Détecte et coupe les boucles d'appels d'outils répétés."},
]
HOOK_NAMES = {h["name"] for h in HOOKS}

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Engine-level tools, always available even when absent from the registry listing.
SYSTEM_TOOLS = {"Methodology", "Snippet", "FinalAnswer"}


def unknown_selections(data: dict) -> str:
    """Why this profile could not run as declared, or "" when every selection exists.

    A profile naming a tool, skill or hook that does not exist would be saved with
    that selection silently dropped — the agent then runs without what it was given.
    """
    import bouzecode.backend.tools.registration  # noqa: F401  (side effect: registers builtins)
    from bouzecode.backend.core.tool_registry import get_all_tools
    from bouzecode.backend.tools.skill.loader import load_skills

    catalog = {
        "outil": ({tool.name for tool in get_all_tools()} | SYSTEM_TOOLS, data.get("tools")),
        "skill": ({skill.name for skill in load_skills()}, data.get("skills")),
        "hook": (HOOK_NAMES, data.get("hooks")),
    }
    problems: list[str] = []
    for label, (available, requested) in catalog.items():
        if not isinstance(requested, list):
            continue
        for item in requested:
            entry = str(item).strip()
            if entry and entry.removeprefix("no-") not in available:
                problems.append(f"{label} inconnu : {entry}")
    return " ; ".join(problems)


def first_line(text: str) -> str:
    return (text or "").strip().split("\n", 1)[0].strip().strip('"')[:120]


def serialize(profile) -> dict:
    return {
        "name": profile.name,
        "description": getattr(profile, "description", "") or "",
        "skills": list(profile.skills),
        "tools": list(profile.tools),
        "hooks": list(profile.hooks),
        "requires_plugins": list(getattr(profile, "requires_plugins", [])),
        "model": profile.model,
        "system_prompt_extra": profile.system_prompt_extra,
    }


def clean_list(value, allowed: set | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        s = str(item).strip()
        if not s:
            continue
        if allowed is not None and s.removeprefix("no-") not in allowed:
            continue
        out.append(s)
    return out


def clean_plugins(value) -> list:
    """Sanitize requires_plugins: keep {name[, source]} dicts, coerce bare names
    to strings. Drops entries without a name."""
    if not isinstance(value, list):
        return []
    out: list = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("package") or "").strip()
            if not name:
                continue
            entry = {"name": name}
            source = str(item.get("source") or "").strip()
            if source:
                entry["source"] = source
            out.append(entry)
        else:
            s = str(item).strip()
            if s:
                out.append(s)
    return out
