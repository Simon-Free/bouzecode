# [desc] Merges multiple AgentProfile instances using ordered union for lists and last-wins for model. [/desc]
from __future__ import annotations

from bouzecode.backend.profiles.models import AgentProfile


def merge_profiles(profiles: list[AgentProfile]) -> AgentProfile:
    """Merge N profiles into one resolved AgentProfile.

    Rules:
    - skills, tools, hooks: ordered union (preserves first-seen order, deduplicates)
    - model: last non-empty value wins
    - system_prompt_extra: concatenated in order, separated by double newline
    """
    if not profiles:
        return AgentProfile()

    skills = _union_lists([p.skills for p in profiles])
    tools = _union_lists([p.tools for p in profiles])
    hooks = _union_lists([p.hooks for p in profiles])
    requires_plugins = _union_plugins([p.requires_plugins for p in profiles])

    model = ""
    for p in profiles:
        if p.model:
            model = p.model

    prompts = [p.system_prompt_extra for p in profiles if p.system_prompt_extra]
    system_prompt_extra = "\n\n".join(prompts)

    # plan_mode: disabled if ANY merged profile opts out (a merged fragment can
    # never silently re-enable plan mode for a dispatcher that turned it off).
    plan_mode = all(p.plan_mode for p in profiles)

    # require_recap: enabled if ANY merged profile requires it (a coder fragment
    # merged onto a base profile must still enforce the recap gate).
    require_recap = any(p.require_recap for p in profiles)

    return AgentProfile(
        name="+".join(p.name for p in profiles if p.name) or "merged",
        skills=skills,
        tools=tools,
        hooks=hooks,
        requires_plugins=requires_plugins,
        model=model,
        system_prompt_extra=system_prompt_extra,
        plan_mode=plan_mode,
        require_recap=require_recap,
    )


def _union_lists(lists: list[list[str]]) -> list[str]:
    """Ordered union: preserves first-seen order, deduplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for lst in lists:
        for item in lst:
            if item not in seen:
                seen.add(item)
                result.append(item)
    return result


def _union_plugins(lists: list[list]) -> list:
    """Ordered union of requires_plugins entries (str or {name, source}),
    deduplicated by plugin name, first-seen wins."""
    seen: set[str] = set()
    result: list = []
    for lst in lists:
        for item in lst:
            key = item.get("name") or item.get("package") if isinstance(item, dict) else item
            if key and key not in seen:
                seen.add(key)
                result.append(item)
    return result
