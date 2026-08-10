# [desc] Agent-builder backend (global): catalogue tools/skills/hooks bouzecode + CRUD des profils d'agent dans ~/.bouzecode/profiles, accessibles partout. [/desc]
"""Compose a specialized agent from the UI. Profiles are saved GLOBALLY in
~/.bouzecode/profiles/<name>.yaml so the agent is usable everywhere (the CLI /agent
command and the sub-agent spawner both read this dir via profiles.discovery).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from bouzecode.backend.profiles import load_profiles_from_dir, load_profile_from_path, user_global_dir
from .profile_io import (
    HOOKS, HOOK_NAMES, NAME_RE,
    first_line, serialize, clean_list, clean_plugins, unknown_selections,
)


def catalog() -> dict:
    """Everything the builder offers: available tools (from the registry, including
    plugin tools registered at startup), skills, hooks and installed plugins."""
    import bouzecode.backend.tools.registration  # noqa: F401  (side effect: registers builtins)
    from bouzecode.backend.core.tool_registry import get_all_tools
    from bouzecode.backend.tools.skill.loader import load_skills

    # Tools that are ALWAYS available (engine-level, cannot be disabled)
    _SYSTEM_TOOLS = {"Methodology", "Snippet", "FinalAnswer"}

    # Built-in tools from the registry (plugins register here too at startup)
    tools: list[dict] = []
    for t in get_all_tools():
        tools.append({
            "name": t.name,
            "description": first_line(t.schema.get("description", "")),
            "read_only": bool(getattr(t, "read_only", False)),
            "system": t.name in _SYSTEM_TOOLS,
        })

    # Skills from the skill loader
    skills: list[dict] = []
    for s in load_skills():
        skills.append({
            "name": s.name,
            "description": first_line(s.description),
            "source": getattr(s, "source", ""),
        })

    from . import plugins as plugins_svc
    return {"tools": tools, "skills": skills, "hooks": list(HOOKS),
            "plugins": plugins_svc.list_installed()}


def preview_prompt(data: dict) -> dict:
    """The full system prompt an agent with these selections would actually receive
    (base identity + skills section + the custom part), plus the runtime-only bits.

    Note: tools and hooks are NOT part of the prompt text — tools are sent as a separate
    API field and hooks act at runtime — so they're returned separately, not inlined."""
    from bouzecode.backend.core.context import build_system_prompt

    extra = (data.get("system_prompt_extra") or "").strip()
    skills = clean_list(data.get("skills"))
    config = {
        "model": (data.get("model") or ""),
        "_agent_system_prompt_extra": extra,
        "_profile_skills": skills,  # preloaded into the prompt, so the preview shows them
    }
    return {
        "system_prompt": build_system_prompt(config),
        "custom_marker": "# Active agent profile",
        "custom": extra,
        "runtime": {
            "tools": clean_list(data.get("tools")),
            "hooks": clean_list(data.get("hooks"), allowed=HOOK_NAMES),
            "skills": skills,
        },
    }


def _profiles_dir() -> Path:
    return user_global_dir()


def list_profiles() -> list[dict]:
    """All global agent profiles, usable everywhere as agent typologies."""
    return [serialize(p) for p in load_profiles_from_dir(_profiles_dir()).values()]


def get_profile(name: str) -> dict | None:
    for ext in (".yaml", ".yml"):
        path = _profiles_dir() / f"{name}{ext}"
        if path.is_file():
            return serialize(load_profile_from_path(path))
    return None


def save_profile(data: dict) -> dict | str:
    """Write ~/.bouzecode/profiles/<name>.yaml. Returns the saved dict or an error string."""
    name = (data.get("name") or "").strip()
    if not NAME_RE.match(name):
        return "nom invalide : minuscules, chiffres, - et _ uniquement"
    problem = unknown_selections(data)
    if problem:
        return problem

    profile = {
        "name": name,
        "description": (data.get("description") or "").strip(),
        "skills": clean_list(data.get("skills")),
        "tools": clean_list(data.get("tools")),
        "hooks": clean_list(data.get("hooks"), allowed=HOOK_NAMES),
        "requires_plugins": clean_plugins(data.get("requires_plugins")),
        "model": (data.get("model") or "").strip(),
        "system_prompt_extra": (data.get("system_prompt_extra") or "").strip(),
    }
    directory = _profiles_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.yaml").write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return profile


def delete_profile(name: str) -> bool:
    for ext in (".yaml", ".yml"):
        path = _profiles_dir() / f"{name}{ext}"
        if path.is_file():
            path.unlink()
            return True
    return False


_SYSTEM_TOOLS = {"Methodology", "Snippet", "FinalAnswer"}


def list_agents() -> list[dict]:
    """All existing agents the user can view/clone: system builtins + profiles (by source).

    Each entry is self-contained (full fields) so the UI can load it without a second
    request. `editable` is True only for global profiles (others load as a clone)."""
    from pathlib import Path
    from bouzecode.backend.core.paths import get_extra_dirs
    from bouzecode.backend.profiles.discovery import load_system_profiles
    import bouzecode.backend.tools.registration  # noqa: F401  (side effect: ensures tools registered)
    from bouzecode.backend.core.tool_registry import get_all_tools

    out: list[dict] = []
    seen: set[str] = set()

    def _emit(name: str, profile, kind: str, source: str, editable: bool) -> None:
        entry = {**serialize(profile), "kind": kind, "source": source, "editable": editable}
        # The 'default' profile means "no restriction" → show every registered tool.
        if not entry["tools"] and name == "default":
            entry["tools"] = [t.name for t in get_all_tools()]
        for st in _SYSTEM_TOOLS:  # Methodology/Snippet/FinalAnswer are always available
            if st not in entry["tools"]:
                entry["tools"].append(st)
        out.append(entry)

    # System builtins (general-purpose / meta-agent / manager) — viewable, clone to edit.
    for name, profile in load_system_profiles().items():
        seen.add(name)
        _emit(name, profile, kind="système", source="built-in", editable=False)

    sources = [("global", user_global_dir()), ("projet", Path.cwd() / ".bouzecode" / "profiles")]
    sources += [("extra", d / "profiles") for d in get_extra_dirs()]
    for label, directory in sources:
        for name, profile in load_profiles_from_dir(directory).items():
            if name in seen:
                continue
            seen.add(name)
            _emit(name, profile, kind="profil", source=label, editable=(label == "global"))

    out.sort(key=lambda a: (a["kind"], a["name"]))
    return out
