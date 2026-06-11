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

    model = ""
    for p in profiles:
        if p.model:
            model = p.model

    prompts = [p.system_prompt_extra for p in profiles if p.system_prompt_extra]
    system_prompt_extra = "\n\n".join(prompts)

    return AgentProfile(
        name="+".join(p.name for p in profiles if p.name) or "merged",
        skills=skills,
        tools=tools,
        hooks=hooks,
        model=model,
        system_prompt_extra=system_prompt_extra,
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
