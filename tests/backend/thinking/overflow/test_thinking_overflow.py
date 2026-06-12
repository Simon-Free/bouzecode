# [desc] Tests the anti-analysis-paralysis thinking overflow mechanism detection and configuration defaults
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests the anti-analysis-paralysis thinking overflow mechanism detection and configuration defaults</param></tool_use> [/desc]
"""Tests for the anti-analysis-paralysis thinking overflow mechanism."""
import pytest

from unittest.mock import MagicMock
from bouzecode.backend.agent.loop_context import LoopContext
from bouzecode.backend.core.config import DEFAULTS


def test_loop_context_has_thinking_overflow_field():
    ctx = LoopContext()
    assert ctx.thinking_overflow is False


def test_thinking_overflow_limit_in_defaults():
    assert "thinking_overflow_limit" in DEFAULTS
    assert DEFAULTS["thinking_overflow_limit"] == 20000


@pytest.mark.skip(reason="Depends on bouzecode.web.runner (not ported to OSS)")
def test_runner_command_includes_loud():
    """Verify that web agent runner builds command with --loud flag."""
    pass


def test_stream_llm_turn_triggers_overflow():
    """Verify that thinking overflow is detected during streaming."""
    from bouzecode.backend.agent.loop_turn import stream_llm_turn
    from bouzecode.backend.agent.loop_context import LoopContext
    from bouzecode.backend.agent.providers import ThinkingChunk, TextChunk, AssistantTurn, StreamStarted

    ctx = LoopContext()
    config = {"model": "test", "thinking_overflow_limit": 100, "_session_id": "test"}

    # Mock state
    state = MagicMock()
    state.timing_entries = []
    state.thinking_log = []
    state.last_api_payload = None

    # We need to mock the stream and _build_messages_for_api
    chunks = [StreamStarted()] + [ThinkingChunk(text="x" * 50) for _ in range(3)]

    import bouzecode.backend.agent.loop_turn as lt
    orig_build = lt._build_messages_for_api
    orig_stream = lt.stream
    orig_schemas = lt.get_tool_schemas
    orig_dump = lt.dump_turn_payload

    lt._build_messages_for_api = lambda s, c: []
    lt.get_tool_schemas = lambda: []
    lt.dump_turn_payload = lambda *a, **kw: None

    def fake_stream(**kwargs):
        yield from chunks

    lt.stream = fake_stream

    try:
        events = list(stream_llm_turn(state, config, "system", ctx, cancel_check=None))
        assert ctx.thinking_overflow is True
        # Should have received some ThinkingChunks before overflow
        assert len(ctx.thinking_parts) > 0
        total_chars = sum(len(p) for p in ctx.thinking_parts)
        assert total_chars > 100
    finally:
        lt._build_messages_for_api = orig_build
        lt.stream = orig_stream
        lt.get_tool_schemas = orig_schemas
        lt.dump_turn_payload = orig_dump
