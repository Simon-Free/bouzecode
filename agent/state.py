# [desc] Dataclass definitions for agent state, tool events, turn metrics, and control signals. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    turn_count: int = 0
    timing_entries: list = field(default_factory=list)
    conversation_start: float = 0.0
    compaction_log: list = field(default_factory=list)
    distinct_base: int = 0


@dataclass
class ToolStart:
    name: str
    inputs: dict


@dataclass
class ToolEnd:
    name: str
    result: str
    permitted: bool = True
    duration: float = 0.0


@dataclass
class TurnDone:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class PermissionRequest:
    description: str
    granted: bool = False


@dataclass
class CheckpointReady:
    message_count: int
