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
    last_usage: Any = None
    # Numéro du dernier tour déjà compté par loop._account_llm_call (garde anti-double compte).
    accounted_turn: int = -1
    # Usage réellement compté pour ce tour (estimations comprises) : (in, out, cache lu,
    # cache écrit, entrée estimée, sortie estimée). C'est lui que porte TurnDone.
    accounted_usage: Any = None
    loop_detector: Any = None
    action: TurnAction = TurnAction.PROCEED
    assistant_turn: Any = None
    thinking_parts: list[str] = field(default_factory=list)
    thinking_overflow: bool = False
    thinking_chars: int = 0
    text_parts: list[str] = field(default_factory=list)
    meta_only_continues: int = 0
    # Content fingerprint of the previous meta-only batch. Two identical ones in
    # a row mean the model is rewriting the same note instead of advancing —
    # that repetition, not the meta-only shape itself, is what closes a session.
    meta_only_signature: str | None = None
    empty_turn_nudges: int = 0

    readonly_streak: int = 0
    turn_tool_schemas: list = field(default_factory=list)  # schemas used for current turn's LLM call
    pending_tool_parsed: list = field(default_factory=list)
    _final_tool_calls: list[dict] = field(default_factory=list)
    system_blocks: list = field(default_factory=list)
    # Empreintes du préfixe envoyé ce tour (SystemPayload), journalisées dans `llm_call`.
    empreinte: Any = None
    interrupted: bool = False
    # --- Anti-premature-close fields (fix compliance/meta-only closures) ---
    # True once any productive tool (Write/Edit/Bash/RunPythonTest/…) executes in this session.
    has_productive_turn: bool = False

    # Number of FinalAnswer nudges sent when text_closes triggers with FinalAnswer available.
    # At >=2 we force-close anyway.
    final_answer_nudges: int = 0
    # Counter for consecutive no-tool turns recovered via side-call (reset on any
    # turn that produces tool_calls). At >=3, fallback to bounce+close for termination.
    consecutive_no_tool_recoveries: int = 0
    # Counter for turns where <tool_use> XML was emitted but parsed to zero calls
    # because it sat inside a ``` fence or a <thinking> region (both treated as
    # inert text by the XML parser). Re-prompt to re-emit raw; reset on any turn
    # that produces tool_calls. Capped so a model that keeps malforming still ends.
    swallowed_xml_nudges: int = 0
    # Consecutive TOTALLY EMPTY turns (no text, no thinking, no tool call). Reset on
    # any turn that produces tool_calls. Last-resort circuit breaker: whatever nudge
    # path is taken above, a run must never chain N byte-identical sterile turns
    # (observed 2026-08-26: three agents burned 184K-266K tokens at ~0.2s/turn on empty
    # completions). Deliberately NOT counting text-only/thinking-only turns: those have
    # a legitimate 10-nudge budget (MAX_FA_NUDGES) so a planning phase is never forced
    # to close early.
    sterile_turns: int = 0
