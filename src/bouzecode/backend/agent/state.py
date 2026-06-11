# [desc] Dataclass definitions for agent state, tool events, turn metrics, and control signals. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field

from ..context_manager import GCState


@dataclass
class AgentState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    turn_count: int = 0
    user_loop_count: int = 0
    total_tool_calls: int = 0
    meta_only_nudges: int = 0
    timing_entries: list = field(default_factory=list)
    conversation_start: float = 0.0
    compaction_log: list = field(default_factory=list)
    distinct_base: int = 0
    gc_state: GCState = field(default_factory=GCState)
    notes_timeline: list = field(default_factory=list)
    last_api_payload: list = field(default_factory=list)
    thinking_log: list = field(default_factory=list)
    system_prompt: str = ""
    bouzecode_commit: str = ""
    bouzecode_version: str = ""
    final_answer: str = ""  # set by the FinalAnswer tool (explicit close signal)
    close_reason: str = ""  # telemetry: which branch closed the session

    # New-model name for gc_state (same object; survivors/tests use context_state).
    @property
    def context_state(self) -> GCState:
        return self.gc_state

    @context_state.setter
    def context_state(self, value: GCState) -> None:
        self.gc_state = value


@dataclass
class ToolStart:
    name: str
    inputs: dict
    tool_id: str = ""


@dataclass
class ToolEnd:
    name: str
    result: str
    permitted: bool = True
    duration: float = 0.0
    tool_id: str = ""
    inputs: dict = field(default_factory=dict)


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
