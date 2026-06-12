# [desc] Tests that methodology notes survive wire transmission to the LLM across multiple turns via dispatch.stream
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that methodology notes survive wire transmission to the LLM across multiple turns via dispatch.stream</param></tool_use> [/desc]
"""Multi-turn reproduction of bouzecode losing its context.

The methodology-centric wire (minimal_payload) DROPS every prior user message
from the message list, on the contract that they live in the methodology
system block instead (as ## User blocks). So the methodology block is the ONLY
carrier of cross-turn context. If it is not transmitted, the model sees
nothing from earlier turns — exactly the "perd son contexte" symptom.

These tests drive the REAL provider path (dispatch.stream), which yields a
SystemPayload with the assembled system_blocks before any network call. We
inspect that payload and assert the methodology made it onto the wire.
"""
from __future__ import annotations

from bouzecode.backend.agent.providers.backends import dispatch
from bouzecode.backend.agent.providers.types import SystemPayload
from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE
from bouzecode.backend.context_manager.methodology import (
    append_user_msg_to_methodology,
    methodology_tool,
)


def _wire_system_text(context_state: ContextState) -> str:
    """Run dispatch.stream just far enough to capture the SystemPayload, then
    return the concatenated text of every system block sent to the API."""
    config = {"anthropic_api_key": "test-key", "_context_state": context_state}
    gen = dispatch.stream(
        model="claude-sonnet-4-6",
        system="SYSTEM PROMPT",
        messages=[{"role": "user", "content": "latest user message"}],
        tool_schemas=[],
        config=config,
    )
    for event in gen:
        if isinstance(event, SystemPayload):
            gen.close()  # never reach the (blocked) network call
            return "\n".join(b.get("text", "") for b in event.system_blocks)
    raise AssertionError("dispatch.stream never yielded a SystemPayload")


def test_methodology_note_reaches_the_wire():
    """A methodology note must appear in the system blocks sent to the API."""
    context_state = ContextState()
    context_state.notes[METHODOLOGY_NOTE] = "## Task\nFIND_THIS_METHODOLOGY_MARKER"

    system_text = _wire_system_text(context_state)

    assert "FIND_THIS_METHODOLOGY_MARKER" in system_text, (
        "Methodology note was NOT transmitted to the LLM. The system blocks "
        "carried no methodology — the model loses all cross-turn context."
    )


def test_multi_turn_user_prompts_and_methodology_survive():
    """Simulate a multi-turn conversation: each user prompt is auto-appended to
    the methodology, plus an explicit Methodology() call. After several turns,
    ALL of it must reach the wire (it is the only carrier — minimal_payload
    drops prior user messages from the message list)."""
    context_state = ContextState()
    config = {"_context_state": context_state}

    append_user_msg_to_methodology(context_state, "USER_PROMPT_TURN_ONE")
    methodology_tool({"content": "PLAN_NOTE_FROM_TURN_ONE"}, config)
    append_user_msg_to_methodology(context_state, "USER_PROMPT_TURN_TWO")

    system_text = _wire_system_text(context_state)

    for marker in (
        "USER_PROMPT_TURN_ONE",
        "PLAN_NOTE_FROM_TURN_ONE",
        "USER_PROMPT_TURN_TWO",
    ):
        assert marker in system_text, (
            f"{marker!r} was lost — not present in the system blocks sent to "
            f"the LLM. This is the multi-turn context-loss bug."
        )
