# [desc] Registers Skill, SkillList and SkillGrep tools for invoking, listing and searching reusable prompt-template skills. [/desc]
"""Skill tool: lets the model invoke skills by name via tool call."""
from __future__ import annotations

import re
from pathlib import Path

from ...core.tool_registry import ToolDef, register_tool
from .loader import find_skill, load_skills, resolve_skills, substitute_arguments
from .scope import SCOPE_SEPARATOR


_SKILL_SCHEMA = {
    "name": "Skill",
    "description": (
        "Invoke a named skill (reusable prompt template). "
        "Use SkillList to see available skills and their triggers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (e.g. 'commit', 'review')",
            },
            "args": {
                "type": "string",
                "description": "Arguments to pass to the skill (replaces $ARGUMENTS)",
                "default": "",
            },
        },
        "required": ["name"],
    },
}

_SKILL_LIST_SCHEMA = {
    "name": "SkillList",
    "description": "List all available skills with their names, triggers, and descriptions.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


_SKILL_GREP_SCHEMA = {
    "name": "SkillGrep",
    "description": (
        "Search the CONTENT of skills with a regex pattern (not just list them). "
        "Returns matching skills and the lines that matched."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern searched in the raw content of each skill's .md file (frontmatter included).",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive search (default true).",
                "default": True,
            },
        },
        "required": ["pattern"],
    },
}


def _skill_content(s) -> str:
    """Full raw text of the skill's .md file (frontmatter included).

    Falls back to the parsed prompt body for skills without a real file
    (e.g. builtins with an empty/nonexistent file_path).
    """
    path = getattr(s, "file_path", "") or ""
    if path:
        try:
            p = Path(path)
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except OSError:
            pass
    return s.prompt


def _grep_skills(skills: list, pattern: str, ignore_case: bool = True) -> str:
    """Pure regex search over the CONTENT of each skill's .md file.

    Reads the whole file (frontmatter included) so name/description/triggers
    are searchable, not just the prompt body. Returns a formatted report.
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return "Error: empty pattern."
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        return f"Error: invalid regex '{pattern}': {exc}"

    blocks: list[str] = []
    for s in skills:
        matched: list[str] = []
        for idx, line in enumerate(_skill_content(s).splitlines(), start=1):
            if rx.search(line):
                matched.append(f"  L{idx}: {line.strip()}")
        if matched:
            blocks.append(f"- **{s.name}** ({s.file_path})\n" + "\n".join(matched))

    if not blocks:
        return f"No skills matched pattern '{pattern}'."
    header = f"Skills matching '{pattern}':\n"
    return header + "\n".join(blocks)


def _skill_grep_tool(params: dict, config: dict) -> str:
    pattern = params.get("pattern", "")
    ignore_case = params.get("ignore_case", True)
    skills = load_skills()
    if not skills:
        return "No skills available."

    # If the active profile/agent declares specific skills, only search those.
    profile_skills = (config.get("_profile_skills") if config else None) or []
    if profile_skills:
        allowed = set(profile_skills)
        skills = [s for s in skills if s.name in allowed]
        if not skills:
            return f"No skills matched the profile filter ({', '.join(profile_skills)})."

    return _grep_skills(skills, pattern, ignore_case)


def _ambiguity_error(skill_name: str, resolution) -> str:
    """Refuse to pick arbitrarily between equally specific same-named skills."""
    candidates = resolution.candidates_for(skill_name)
    listed = "\n".join(
        f"- {s.scope_label}{SCOPE_SEPARATOR}{s.name} ({s.file_path})" for s in candidates
    )
    return (f"Error: skill '{skill_name}' is ambiguous — several skills of equal scope "
            f"specificity answer to it. Ask for one by its qualified name:\n{listed}")


def _skill_tool(params: dict, config: dict) -> str:
    """Load a skill and return its rendered prompt content directly (no sub-agent)."""
    skill_name = params.get("name", "").strip()
    args = params.get("args", "")

    resolution = resolve_skills()
    if skill_name in resolution.ambiguous and SCOPE_SEPARATOR not in skill_name:
        return _ambiguity_error(skill_name, resolution)

    skill = resolution.by_name(skill_name)
    if skill is None:
        skill = find_skill(skill_name)
    if skill is None:
        names = [s.name for s in resolution.winners]
        return f"Error: skill '{skill_name}' not found. Available: {', '.join(names)}"

    rendered = substitute_arguments(skill.prompt, args, skill.arguments)
    return f"[Skill: {skill.name} | file: {skill.file_path}]\n\n{rendered}"


def _shadowed_section(resolution, visible_names: set) -> str:
    """Name every same-named skill that lost, with both paths. Never resolve in silence."""
    rows = []
    for name in sorted(resolution.shadowed):
        if name not in visible_names:
            continue
        winner = resolution.by_name(name)
        for loser in resolution.shadowed[name]:
            rows.append(f"- **{name}**: {loser.file_path}\n  masquée par {winner.file_path}")
    if not rows:
        return ""
    return ("\n\n## Masquées\n"
            "Ces skills portent un nom déjà pris par une skill de portée plus spécifique. "
            "Ce n'est pas une erreur — c'est une surcharge assumée.\n" + "\n".join(rows))


def _skill_list_tool(params: dict, config: dict) -> str:
    resolution = resolve_skills()
    skills = resolution.winners
    if not skills:
        return "No skills available."

    # If the active profile/agent declares specific skills, only show those.
    profile_skills = (config.get("_profile_skills") if config else None) or []
    if profile_skills:
        allowed = set(profile_skills)
        skills = [s for s in skills if s.name in allowed]
        if not skills:
            return f"No skills matched the profile filter ({', '.join(profile_skills)})."

    lines = ["Available skills:\n"]
    for s in skills:
        triggers = ", ".join(s.triggers)
        hint = f"  args: {s.argument_hint}" if s.argument_hint else ""
        when = f"\n    when: {s.when_to_use}" if s.when_to_use else ""
        label = s.qualified_name or s.name
        lines.append(f"- **{label}** [{triggers}]{hint}\n  {s.description}{when}")
    return "\n".join(lines) + _shadowed_section(resolution, {s.name for s in skills})


def _register() -> None:
    register_tool(ToolDef(
        name="Skill",
        schema=_SKILL_SCHEMA,
        func=_skill_tool,
        read_only=True,
        concurrent_safe=True,
    ))
    register_tool(ToolDef(
        name="SkillList",
        schema=_SKILL_LIST_SCHEMA,
        func=_skill_list_tool,
        read_only=True,
        concurrent_safe=True,
    ))
    register_tool(ToolDef(
        name="SkillGrep",
        schema=_SKILL_GREP_SCHEMA,
        func=_skill_grep_tool,
        read_only=True,
        concurrent_safe=True,
    ))


_register()
