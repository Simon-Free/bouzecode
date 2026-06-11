# [desc] Dataclass defining AgentProfile with composable skills, tools, hooks, model, and prompt fields. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentProfile:
    """A composable agent profile declaring capabilities."""

    name: str = ""
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    model: str = ""
    system_prompt_extra: str = ""
