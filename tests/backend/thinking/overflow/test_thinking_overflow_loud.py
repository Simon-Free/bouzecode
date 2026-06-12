# [desc] Tests thinking overflow detection in loud mode (TextChunk accumulation) and suppression when tool calls present
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests thinking overflow detection in loud mode (TextChunk accumulation) and suppression when tool calls present</param></tool_use> [/desc]
"""Test thinking overflow in loud mode (TextChunk instead of ThinkingChunk)."""
from unittest.mock import MagicMock
from types import SimpleNamespace

from bouzecode.backend.agent.loop_context import LoopContext
from bouzecode.backend.agent.loop_turn import stream_llm_turn
from bouzecode.backend.agent.providers import TextChunk, AssistantTurn, StreamStarted


def _make_text_chunks(total_chars, chunk_size=500):
    """Generate TextChunk events simulating loud-mode thinking."""
    yield StreamStarted()
    text = "x" * chunk_size
    for _ in range(total_chars // chunk_size + 1):
        yield TextChunk(text=text)
    yield AssistantTurn(text="", tool_calls=[], in_tokens=0, out_tokens=0,
                        cache_read_tokens=0, cache_creation_tokens=0)


def test_stream_llm_turn_triggers_overflow_text_chunks(monkeypatch):
    """Overflow triggers on TextChunk accumulation (loud mode)."""
    from bouzecode.backend.agent import loop_turn

    state = MagicMock()
    state.timing_entries = []
    state.thinking_log = []
    state.last_api_payload = None

    config = {
        "model": "test",
        "thinking_overflow_limit": 5000,
        "thinking_mode": "loud",
    }

    ctx = LoopContext()
    monkeypatch.setattr(loop_turn, "_build_messages_for_api", lambda s, c: [])
    monkeypatch.setattr(loop_turn, "get_tool_schemas", lambda: [])
    monkeypatch.setattr(loop_turn, "dump_turn_payload", lambda *a, **kw: None)

    # Simulate 10000 chars of TextChunk (loud-mode thinking)
    monkeypatch.setattr(loop_turn, "stream", lambda **kw: _make_text_chunks(10000))

    events = list(stream_llm_turn(state, config, "system", ctx, cancel_check=None))

    assert ctx.thinking_overflow is True
    assert ctx.thinking_chars > 5000
    # Should have broken before receiving AssistantTurn
    assert ctx.assistant_turn is None


def test_no_overflow_when_tool_calls_present(monkeypatch):
    """Overflow does NOT trigger if tool calls have been parsed."""
    from bouzecode.backend.agent import loop_turn
    from bouzecode.backend.agent.providers import ToolCallParsed

    state = MagicMock()
    state.timing_entries = []
    state.thinking_log = []
    state.last_api_payload = None

    config = {
        "model": "test",
        "thinking_overflow_limit": 5000,
    }

    def _events():
        yield StreamStarted()
        # First emit a tool call
        yield ToolCallParsed(tool_id="t1", name="Read", inputs={"file_path": "x.py"})
        # Then emit lots of text (> limit)
        for _ in range(20):
            yield TextChunk(text="y" * 500)
        yield AssistantTurn(text="", tool_calls=[{"id": "t1", "name": "Read", "input": {}}],
                            in_tokens=0, out_tokens=0,
                            cache_read_tokens=0, cache_creation_tokens=0)

    ctx = LoopContext()
    monkeypatch.setattr(loop_turn, "_build_messages_for_api", lambda s, c: [])
    monkeypatch.setattr(loop_turn, "get_tool_schemas", lambda: [])
    monkeypatch.setattr(loop_turn, "dump_turn_payload", lambda *a, **kw: None)
    monkeypatch.setattr(loop_turn, "stream", lambda **kw: _events())

    events = list(stream_llm_turn(state, config, "system", ctx, cancel_check=None))

    # Should NOT overflow because tool call was parsed first
    assert ctx.thinking_overflow is False
    assert ctx.assistant_turn is not None
