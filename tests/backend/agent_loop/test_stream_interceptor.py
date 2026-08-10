"""Tests for the official stream interceptor API."""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.stream_interceptor import (
    set_stream_interceptor,
    get_streamer,
)


@pytest.fixture(autouse=True)
def _cleanup_interceptor():
    """Ensure interceptor is cleared after each test."""
    yield
    set_stream_interceptor(None)


# ---------------------------------------------------------------------------
# (a) Interceptor sees main turn AND recovery side-call
# ---------------------------------------------------------------------------

class _Recorder:
    """Interceptor that records all calls going through the stream."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, original_stream):
        recorder = self

        def wrapper(model, system, messages, tool_schemas, config):
            recorder.calls.append({
                "model": model,
                "system": system,
                "messages": messages,
                "tool_schemas": tool_schemas,
                "config": config,
            })
            return original_stream(model, system, messages, tool_schemas, config)

        return wrapper


def test_interceptor_sees_main_and_side_calls(monkeypatch):
    """An interceptor registered via set_stream_interceptor sees both the main
    stream_llm_turn call and the enforcement_call._ask_forced side-call."""
    from bouzecode.backend.agent import loop_turn as _lt
    from bouzecode.backend.agent.enforcement_call import _ask_forced
    from bouzecode.backend.agent.providers import AssistantTurn

    # Minimal fake stream that yields an AssistantTurn with a Methodology tool_call
    def fake_stream(model, system, messages, tool_schemas, config):
        yield AssistantTurn(
            text="done",
            tool_calls=[{"id": "m1", "name": "Methodology",
                         "input": {"content": "hello"}}],
            in_tokens=10, out_tokens=5,
            cache_read_tokens=0, cache_creation_tokens=0,
        )

    # Patch the module-level stream on loop_turn (same as harness does)
    monkeypatch.setattr(_lt, "stream", fake_stream)

    recorder = _Recorder()
    set_stream_interceptor(recorder)

    # 1) Simulate main turn call via get_streamer
    streamer = get_streamer()
    events = list(streamer(
        model="test-model", system="sys", messages=[],
        tool_schemas=[], config={"model": "test-model"},
    ))
    assert len(events) == 1
    assert isinstance(events[0], AssistantTurn)

    # 2) Simulate enforcement side-call via _ask_forced (uses get_streamer internally)
    monkeypatch.setattr(
        "bouzecode.backend.core.tool_registry.get_tool_schemas",
        lambda: [{"name": "Methodology", "parameters": {}}],
    )
    result = _ask_forced(
        "Methodology", "system prompt", "context msg",
        {"model": "test-model"},
    )
    assert len(result) == 1
    assert result[0]["name"] == "Methodology"

    # Both calls recorded
    assert len(recorder.calls) == 2
    assert recorder.calls[0]["model"] == "test-model"
    assert recorder.calls[1]["model"] == "test-model"
    # Side-call has different system prompt
    assert recorder.calls[1]["system"] == "system prompt"


# ---------------------------------------------------------------------------
# (b) set_stream_interceptor(None) restores default
# ---------------------------------------------------------------------------

def test_set_none_restores_default(monkeypatch):
    """After set_stream_interceptor(None), get_streamer returns the raw stream."""
    from bouzecode.backend.agent import loop_turn as _lt

    sentinel = object()

    def my_stream(model, system, messages, tool_schemas, config):
        yield sentinel

    monkeypatch.setattr(_lt, "stream", my_stream)

    # With interceptor
    recorder = _Recorder()
    set_stream_interceptor(recorder)
    streamer = get_streamer()
    assert list(streamer("m", "s", [], [], {})) == [sentinel]
    assert len(recorder.calls) == 1

    # Clear interceptor
    set_stream_interceptor(None)
    streamer = get_streamer()
    result = list(streamer("m", "s", [], [], {}))
    assert result == [sentinel]
    # No new recording
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# (c) Harness mock_llm (monkeypatch on loop_turn.stream) still works
# ---------------------------------------------------------------------------

def test_harness_monkeypatch_still_works(monkeypatch):
    """The e2e harness patches loop_turn.stream directly; get_streamer() picks
    that up dynamically even without an interceptor."""
    from bouzecode.backend.agent import loop_turn as _lt
    from bouzecode.backend.agent.providers import AssistantTurn

    call_log = []

    def harness_stream(model, system, messages, tool_schemas, config):
        call_log.append("called")
        yield AssistantTurn(
            text="harness", tool_calls=[],
            in_tokens=0, out_tokens=0,
            cache_read_tokens=0, cache_creation_tokens=0,
        )

    # Simulate what e2e_harness does
    monkeypatch.setattr(_lt, "stream", harness_stream)

    # No interceptor set — get_streamer should return the patched version
    streamer = get_streamer()
    events = list(streamer("m", "s", [], [], {}))
    assert len(events) == 1
    assert events[0].text == "harness"
    assert call_log == ["called"]


def test_harness_monkeypatch_with_interceptor(monkeypatch):
    """When both harness patch AND interceptor are active, the interceptor
    wraps the patched stream (not the original)."""
    from bouzecode.backend.agent import loop_turn as _lt
    from bouzecode.backend.agent.providers import AssistantTurn

    def harness_stream(model, system, messages, tool_schemas, config):
        yield AssistantTurn(
            text="harness", tool_calls=[],
            in_tokens=0, out_tokens=0,
            cache_read_tokens=0, cache_creation_tokens=0,
        )

    monkeypatch.setattr(_lt, "stream", harness_stream)

    recorder = _Recorder()
    set_stream_interceptor(recorder)

    streamer = get_streamer()
    events = list(streamer("m", "s", [], [], {}))
    assert events[0].text == "harness"
    assert len(recorder.calls) == 1
