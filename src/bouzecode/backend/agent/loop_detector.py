# [desc] Detects repeating cycles in LLM tool call patterns across turns to break infinite loops. [/desc]
"""Tool call loop detector — detects repeating cycles in LLM tool call patterns."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

MAX_CYCLE_SIZE = 8
MIN_REPEATS = 3

# Keys to include in turn signature (skip large content fields like 'content', 'new_source')
SIGNATURE_KEYS = ("name", "file_path", "command", "pattern", "url", "symbol", "query", "old_string")


def _turn_signature(tool_calls: list[dict]) -> str:
    """Create a hashable signature for a turn's tool calls."""
    parts = []
    for tc in sorted(tool_calls, key=lambda x: x.get("name", "")):
        sig = {"name": tc.get("name", "")}
        inputs = tc.get("input", tc.get("params", {}))
        if isinstance(inputs, dict):
            for key in SIGNATURE_KEYS:
                if key != "name" and key in inputs:
                    val = inputs[key]
                    if isinstance(val, str) and len(val) > 200:
                        val = val[:200]
                    sig[key] = val
        parts.append(json.dumps(sig, sort_keys=True))
    combined = "|".join(parts)
    return hashlib.md5(combined.encode()).hexdigest()


@dataclass
class LoopWarning:
    """Event yielded when a tool call loop is detected."""
    cycle_size: int
    repeats: int
    tools: list[str]


@dataclass
class EnforcementWarning:
    """Event yielded when enforcement hooks trigger a retry for missing tools."""
    missing_tools: list[str]


@dataclass
class RecoveryFailed:
    """Event yielded when a best-effort recovery side-call dies (session continues)."""
    tool: str
    error: str


class ToolCallLoopDetector:
    """Detects repeating cycles in tool call patterns across turns."""

    def __init__(self, max_cycle_size: int = MAX_CYCLE_SIZE, min_repeats: int = MIN_REPEATS):
        self.max_cycle_size = max_cycle_size
        self.min_repeats = min_repeats
        self._history: list[str] = []
        self._tool_names_history: list[list[str]] = []

    def record_turn(self, tool_calls: list[dict]) -> None:
        """Record a turn's tool calls as a signature."""
        if not tool_calls:
            return
        sig = _turn_signature(tool_calls)
        self._history.append(sig)
        self._tool_names_history.append([tc.get("name", "?") for tc in tool_calls])

    def check(self) -> LoopWarning | None:
        """Check if recent turns form a repeating cycle. Returns LoopWarning or None."""
        n = len(self._history)
        for cycle_size in range(1, self.max_cycle_size + 1):
            needed = cycle_size * self.min_repeats
            if n < needed:
                continue
            tail = self._history[-needed:]
            pattern = tail[:cycle_size]
            if all(
                tail[i:i + cycle_size] == pattern
                for i in range(cycle_size, needed, cycle_size)
            ):
                tools: list[str] = []
                for names in self._tool_names_history[-cycle_size:]:
                    tools.extend(names)
                # Dedupe preserving order
                seen: set[str] = set()
                unique_tools = [t for t in tools if t not in seen and not seen.add(t)]
                return LoopWarning(
                    cycle_size=cycle_size,
                    repeats=self.min_repeats,
                    tools=unique_tools,
                )
        return None

    def record_and_check(self, tool_calls: list[dict]) -> LoopWarning | None:
        """Record a turn and immediately check for loops."""
        self.record_turn(tool_calls)
        return self.check()

    def reset(self) -> None:
        """Reset history after a loop is detected and handled."""
        self._history.clear()
        self._tool_names_history.clear()
