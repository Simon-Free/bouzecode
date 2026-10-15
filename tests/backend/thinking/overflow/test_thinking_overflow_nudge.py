# [desc] Tests that the thinking overflow notice is neutral (no </thinking>, no reasoning vocabulary) and only informs [/desc]
"""Test that the thinking overflow nudge message has correct format."""
import types
from unittest.mock import MagicMock
from bouzecode.backend.agent.loop_context import LoopContext, TurnAction
from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.providers import AssistantTurn, ThinkingChunk, TextChunk


def _fake_stream_that_overflows(state, config, system_prompt, ctx, cancel_check):
    """Simulate stream_llm_turn setting thinking_overflow."""
    ctx.thinking_overflow = True
    ctx.thinking_chars = 25000
    ctx.thinking_parts = ["x" * 25000]
    ctx.assistant_turn = None
    return
    yield  # make it a generator


def test_nudge_message_is_neutral_notice():
    """The notice injected after overflow is neutral: no tag, no reasoning vocabulary."""
    from bouzecode.backend.agent.state import AgentState
    import bouzecode.backend.agent.loop as loop_mod

    state = AgentState()
    config = {"model": "test", "thinking_overflow_limit": 20000}

    # Patch stream_llm_turn to simulate overflow
    original = loop_mod.stream_llm_turn
    call_count = [0]

    def patched_stream(s, c, sp, ctx, cc):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: simulate overflow
            ctx.thinking_overflow = True
            ctx.thinking_chars = 25000
            ctx.thinking_parts = ["analyze " * 3000]
            ctx.assistant_turn = None
            return
            yield
        else:
            # Second call: return a normal turn with no tools to end loop
            ctx.assistant_turn = AssistantTurn(
                text="I'll act now.", tool_calls=[],
                in_tokens=100, out_tokens=50,
                cache_read_tokens=0, cache_creation_tokens=0,
            )
            return
            yield

    loop_mod.stream_llm_turn = patched_stream
    try:
        events = list(run("test prompt", state, config, "system", depth=0))
    finally:
        loop_mod.stream_llm_turn = original

    # Find the nudge message in state.messages
    nudge_msgs = [m for m in state.messages if m["role"] == "user" and "interrompu" in m.get("content", "")]
    assert len(nudge_msgs) >= 1, f"No nudge message found. Messages: {[m['content'][:80] for m in state.messages]}"

    nudge = nudge_msgs[0]["content"]
    # No `</thinking>` sent to the model: the cut assistant turn is stored closed and stripped
    # from the wire, and the tag trips claude-opus-5's refusal classifier (2026-09-29).
    assert "</thinking>" not in nudge, nudge
    # Pure information: says the turn was cut, never how to reason or act
    assert nudge.startswith("[SYSTEM] Tour précédent interrompu (longueur : 25000 caractères)"), nudge
    for instruction in ("STOP DELIBERATING", "ACT NOW", "AGIS", "re-déroule", "test_*.py"):
        assert instruction not in nudge, f"Nudge must not instruct ({instruction!r}): {nudge}"
