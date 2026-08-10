# [desc] Test helper: build real Anthropic SSE event objects and replay them through stream_anthropic without a socket. [/desc]
"""Replay a scripted Anthropic SSE stream through the real `stream_anthropic`.

`mock_api` (tests/mock_anthropic_server.py) cannot serve native `tool_use` blocks and
its threaded-werkzeug server is skipped on Windows, so transport-level native tests
need another route. Here only the transport seam is replaced: the SSE events are REAL
Anthropic SDK objects (pydantic-validated, so a test passes only if the SDK really
exposes the fields the streamer reads) and the accumulator, XML parser, wire conversion
and AssistantTurn assembly all execute for real.

Event shapes are copied from real SSE dumps captured against the
Anthropic Messages API (2026-07-27).
"""
from __future__ import annotations

from pydantic import TypeAdapter
from anthropic.types import RawMessageStreamEvent

# Bound at import time, i.e. before the autouse live-API guard rebinds the module
# attribute. This is the real streamer; replay_stream swaps its transport seam so
# nothing ever leaves the process.
from bouzecode.backend.agent.providers.backends.anthropic_stream import (
    stream_anthropic as _real_stream_anthropic,
)
from bouzecode.backend.agent.providers import ToolCallParsed, AssistantTurn

_ADAPTER = TypeAdapter(RawMessageStreamEvent)


def sse(*payloads) -> list:
    """Validate raw SSE payloads into real SDK event objects."""
    return [_ADAPTER.validate_python(p) for p in payloads]


def opening():
    return [{"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "content": [],
        "model": "claude-opus-4-8", "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 0}}}]


def text(index, body):
    return [
        {"type": "content_block_start", "index": index,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": index,
         "delta": {"type": "text_delta", "text": body}},
        {"type": "content_block_stop", "index": index},
    ]


def tool_open(index, tool_id, name):
    return {"type": "content_block_start", "index": index,
            "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}}}


def args(index, fragment):
    """One `input_json_delta`, cut at whatever boundary the server chose."""
    return {"type": "content_block_delta", "index": index,
            "delta": {"type": "input_json_delta", "partial_json": fragment}}


def close(index):
    return {"type": "content_block_stop", "index": index}


def closing(stop_reason="tool_use"):
    return [{"type": "message_delta",
             "delta": {"stop_reason": stop_reason, "stop_sequence": None},
             "usage": {"output_tokens": 42}}]


def replay_stream(monkeypatch, events, native_tools, messages=None, sent=None):
    """Run the real stream_anthropic over `events`; return everything it yielded.

    `sent`, when given a list, collects the request kwargs actually built for the API.
    """
    import bouzecode.backend.agent.providers.backends.anthropic_stream as streamer

    class _FakeStream:
        def __enter__(self):
            return events

        def __exit__(self, *exc):
            return False

    def _fake_create(client, kwargs):
        if sent is not None:
            sent.append(kwargs)
        return _FakeStream()

    monkeypatch.setattr(streamer, "_create_anthropic_stream_with_retry", _fake_create)
    return list(_real_stream_anthropic(
        api_key="test-key", model="claude-opus-4-8",
        system=[{"type": "text", "text": "system prefix"}],
        messages=messages or [{"role": "user", "content": "vas-y"}],
        tool_schemas=[], config={}, native_tools=native_tools,
    ))


def tool_calls_of(yielded):
    return [e for e in yielded if isinstance(e, ToolCallParsed)]


def turn_of(yielded):
    return next(e for e in yielded if isinstance(e, AssistantTurn))
