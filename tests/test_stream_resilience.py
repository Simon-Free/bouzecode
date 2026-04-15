# [desc] Tests stream resilience helpers against malformed SSE events with JSON/Unicode decode errors. [/desc]
"""Tests for stream resilience against malformed SSE events.

Scenario: an upstream proxy in front of Anthropic can send SSE events with
empty or corrupt `data:` payloads. The Anthropic SDK then raises
JSONDecodeError (or UnicodeDecodeError) mid-stream, which used to kill
the whole turn with a traceback.

Goal: the resilient iterator must log the issue and stop cleanly so the
caller can still emit a partial AssistantTurn.
"""
from __future__ import annotations

import json

import httpx
import pytest

from providers import (
    _iter_stream_resilient, _install_sse_diagnostic_patch, _StreamInterrupted,
)


def test_resilient_iter_stops_on_json_decode_error():
    events_collected = []
    warnings = []

    def _bad_stream():
        yield "event-1"
        yield "event-2"
        raise json.JSONDecodeError("Expecting value", "", 0)

    for ev in _iter_stream_resilient(_bad_stream(), warnings.append):
        events_collected.append(ev)

    assert events_collected == ["event-1", "event-2"]
    assert len(warnings) == 1
    assert "malformed SSE event" in warnings[0]
    assert "JSONDecodeError" in warnings[0]


def test_resilient_iter_stops_on_unicode_decode_error():
    warnings = []

    def _bad_stream():
        yield "ok"
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    collected = list(_iter_stream_resilient(_bad_stream(), warnings.append))

    assert collected == ["ok"]
    assert len(warnings) == 1
    assert "UnicodeDecodeError" in warnings[0]


def test_resilient_iter_raises_on_httpx_read_error():
    warnings = []

    def _bad_stream():
        yield "ok-1"
        raise httpx.ReadError("WinError 10054: connection reset by host")

    collected = []
    with pytest.raises(_StreamInterrupted):
        for ev in _iter_stream_resilient(_bad_stream(), warnings.append):
            collected.append(ev)

    assert collected == ["ok-1"]
    assert len(warnings) == 1
    assert "upstream closed" in warnings[0]
    assert "ReadError" in warnings[0]


def test_resilient_iter_passes_through_clean_stream():
    warnings = []
    collected = list(_iter_stream_resilient(iter(range(3)), warnings.append))
    assert collected == [0, 1, 2]
    assert warnings == []


def test_sse_diagnostic_patch_logs_and_reraises(capsys):
    """The SDK patch must log the raw SSE preview before re-raising."""
    _install_sse_diagnostic_patch()
    from anthropic._streaming import ServerSentEvent

    sse = ServerSentEvent(event="content_block_delta", data="", id="e_123", retry=None)
    try:
        sse.json()
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("expected JSONDecodeError")

    err = capsys.readouterr().err
    assert "[sse-diag]" in err
    assert "content_block_delta" in err
    assert "e_123" in err
