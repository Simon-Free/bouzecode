# [desc] Defines ContextState dataclass and resolver for per-run agent context/notes state. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field


METHODOLOGY_NOTE = "methodology"


@dataclass
class ContextState:
    notes: dict = field(default_factory=dict)
    deferred_queue: list = field(default_factory=list)


def resolve_context_state(config: dict) -> "ContextState | None":
    """Read the per-run state object from config under "_context_state"."""
    return config.get("_context_state")
