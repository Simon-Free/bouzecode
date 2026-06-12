# [desc] Tests that the thinking overflow nudge message starts with </thinking> and contains required keywords
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that the thinking overflow nudge message starts with </thinking> and contains required keywords</param></tool_use> [/desc]
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


def test_nudge_message_starts_with_closing_thinking_tag():
    """The nudge injected after overflow must start with </thinking> to close model's open block."""
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
    nudge_msgs = [m for m in state.messages if m["role"] == "user" and "thinking" in m.get("content", "").lower()]
    assert len(nudge_msgs) >= 1, f"No nudge message found. Messages: {[m['content'][:80] for m in state.messages]}"

    nudge = nudge_msgs[0]["content"]
    # Must start with </thinking> to close model's thinking block
    assert nudge.startswith("</thinking>"), f"Nudge must start with '</thinking>', got: {nudge[:60]}"
    # Must mention writing tests
    assert "test" in nudge.lower(), f"Nudge must mention tests, got: {nudge}"
    # Must mention hypothesis
    assert "hypoth" in nudge.lower(), f"Nudge must mention hypotheses, got: {nudge}"
