# [desc] Registers Skill, SkillResearch and SkillGrep tools for invoking and searching reusable prompt-template skills. [/desc]
"""Skill tool: lets the model invoke skills by name via tool call."""
from __future__ import annotations

import re
from pathlib import Path

from ...core.tool_registry import ToolDef, register_tool
from .loader import find_skill, load_skills, resolve_skills, substitute_arguments
from .research import SCHEMA as _SKILL_RESEARCH_SCHEMA, skill_research
from .scope import SCOPE_SEPARATOR


_SKILL_SCHEMA = {
    "name": "Skill",
    "description": (
        "Invoke a named skill (reusable prompt template). "
        "Find skills by keyword with SkillResearch(query=...)."
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
        return (f"Error: skill '{skill_name}' not found.\n"
                + skill_research({"query": skill_name.replace("-", " "), "limit": 5}, config))

    rendered = substitute_arguments(skill.prompt, args, skill.arguments)
    # Le bandeau de fraîcheur passe AVANT le contenu : lu après, il arriverait trop tard,
    # l'agent ayant déjà pris la skill pour argent comptant. Vide quand rien n'a dérivé.
    from .freshness import banner
    from .conservation import conserver_dans_la_note

    tete = f"[Skill: {skill.name} | file: {skill.file_path}]\n\n"
    avis, deja_chargee = conserver_dans_la_note(skill, args, config)
    if deja_chargee:
        return f"{tete}{banner(skill)}{avis}"
    if avis:
        tete += f"{avis}\n\n"
    return f"{tete}{banner(skill)}{rendered}"


def _register() -> None:
    register_tool(ToolDef(
        name="Skill",
        schema=_SKILL_SCHEMA,
        func=_skill_tool,
        read_only=True,
        concurrent_safe=True,
        #  Son résultat dépend de la note de travail (déjà conservée ou pas) : jamais
        #  servi par la mémoire anti-répétition.
        etat_externe=True,
    ))
    register_tool(ToolDef(
        name="SkillResearch",
        schema=_SKILL_RESEARCH_SCHEMA,
        func=skill_research,
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
