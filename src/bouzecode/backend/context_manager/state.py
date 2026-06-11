# [desc] GCState dataclass: holds the persistent methodology note across turns. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field


METHODOLOGY_NOTE = "methodology"


@dataclass
class GCState:
    notes: dict = field(default_factory=dict)


# Backwards-compatibility alias used by some tests
ContextState = GCState


def resolve_context_state(config: dict) -> "GCState | None":
    """Read the per-run state object from config under either the new
    ("_context_state") or the legacy ("_gc_state") key — both point to the same
    GCState instance (loop.py sets both)."""
    return config.get("_context_state") or config.get("_gc_state")
