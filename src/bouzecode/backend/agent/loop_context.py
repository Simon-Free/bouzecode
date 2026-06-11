# [desc] Dataclass and enum for mutable loop state shared across loop_turn helper functions. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TurnAction(Enum):
    CONTINUE = "continue"
    BREAK = "break"
    PROCEED = "proceed"


@dataclass
class LoopContext:
    enforcement_retries: int = 0
    enforcement_requested: list[str] = field(default_factory=list)
    blocked_tool_calls: list[dict] = field(default_factory=list)
    required_tool: str | None = None
    required_tool_called: bool = False
    max_nudges: int = 3
    nudge_count: int = 0
    test_enforcement_done: bool = False
    partial_stream: bool = False
    loop_detector: Any = None
    action: TurnAction = TurnAction.PROCEED
    assistant_turn: Any = None
    thinking_parts: list[str] = field(default_factory=list)
    thinking_overflow: bool = False
    thinking_chars: int = 0
    text_parts: list[str] = field(default_factory=list)
    meta_only_continues: int = 0
    empty_turn_nudges: int = 0
    compliance_turn_pending: bool = False
    # Bounce d'un tour thinking-seul (ni texte ni call enregistré) : une émission
    # avalée est possible — accepter la ré-émission au tour de conformité et ne
    # pas clore la session dessus. Jamais posé quand des calls SONT enregistrés
    # (le drop anti-T101 des calls de contrebande reste actif dans ce cas).
    reemit_expected: bool = False
    readonly_streak: int = 0
    turn_tool_schemas: list = field(default_factory=list)  # schemas used for current turn's LLM call
    pending_tool_parsed: list = field(default_factory=list)
    _final_tool_calls: list[dict] = field(default_factory=list)
    system_blocks: list = field(default_factory=list)
    interrupted: bool = False
    # --- Anti-premature-close fields (fix compliance/meta-only closures) ---
    # True once any productive tool (Write/Edit/Bash/RunPythonTest/…) executes in this session.
    has_productive_turn: bool = False
    # Number of times a compliance-close was deferred because no productive turn yet.
    # At >=2 we force-close anyway (anti-eternal-session cap).
    compliance_close_deferrals: int = 0
    # Number of FinalAnswer nudges sent when text_closes triggers with FinalAnswer available.
    # At >=2 we force-close anyway.
    final_answer_nudges: int = 0
    # Counter for consecutive no-tool turns recovered via side-call (reset on any
    # turn that produces tool_calls). At >=3, fallback to bounce+close for termination.
    consecutive_no_tool_recoveries: int = 0
