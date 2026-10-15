# [desc] Tests inter-chunk stall detection and stream interruption in _iter_stream_resilient [/desc]
"""Tests for the inter-chunk stall detection in _iter_stream_resilient."""
import inspect
import threading
import time
import pytest

from bouzecode.backend.agent.providers.backends.anthropic_helpers import (
    _iter_stream_resilient, _StreamInterrupted, _INTER_CHUNK_TIMEOUT_S,
)


class FakeEvent:
    def __init__(self, data):
        self.type = "content_block_delta"
        self.data = data


class StallingStream:
    """A fake stream that yields N events then stalls forever."""

    def __init__(self, events_before_stall: int):
        self._events_before_stall = events_before_stall
        self._stall_event = threading.Event()

    def __iter__(self):
        for i in range(self._events_before_stall):
            yield FakeEvent(f"chunk_{i}")
        self._stall_event.wait()  # block forever (until test ends)

    def unstall(self):
        self._stall_event.set()


class NormalStream:
    """A stream that yields events normally and completes."""

    def __init__(self, count: int):
        self._count = count

    def __iter__(self):
        for i in range(self._count):
            yield FakeEvent(f"chunk_{i}")


class ErrorStream:
    """A stream that yields N events then raises a network error."""

    def __init__(self, events_before_error: int):
        self._events_before_error = events_before_error

    def __iter__(self):
        import httpx
        for i in range(self._events_before_error):
            yield FakeEvent(f"chunk_{i}")
        raise httpx.RemoteProtocolError("peer closed connection")


def _noop_warn(msg):
    pass


def test_normal_stream_completes():
    stream = NormalStream(5)
    events = list(_iter_stream_resilient(stream, _noop_warn))
    assert len(events) == 5
    assert events[0].data == "chunk_0"
    assert events[4].data == "chunk_4"


def test_empty_stream_completes():
    stream = NormalStream(0)
    events = list(_iter_stream_resilient(stream, _noop_warn))
    assert events == []


def test_stall_after_first_event_raises_stream_interrupted():
    """The stall path is exercised with an injected short deadline: waiting the
    full production one would cost a minute for no extra coverage (the
    production default itself is pinned by
    test_inter_chunk_default_is_production_constant)."""
    stream = StallingStream(events_before_stall=2)
    warnings = []

    t0 = time.monotonic()
    with pytest.raises(_StreamInterrupted, match="inter-chunk stall"):
        list(_iter_stream_resilient(
            stream, warnings.append, inter_chunk_timeout_s=0.5,
        ))
    elapsed = time.monotonic() - t0

    stream.unstall()  # cleanup
    assert 0.5 <= elapsed < 3.0
    assert any("no data received" in w for w in warnings)


def test_inter_chunk_default_is_production_constant():
    """Guard: the injectable deadline must still default to the production
    value, so no test can silently weaken the real stall detector."""
    sig = inspect.signature(_iter_stream_resilient)
    param = sig.parameters["inter_chunk_timeout_s"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default == _INTER_CHUNK_TIMEOUT_S
    assert _INTER_CHUNK_TIMEOUT_S >= 30, (
        "production inter-chunk deadline looks far too short"
    )


def test_network_error_raises_stream_interrupted():
    stream = ErrorStream(events_before_error=3)
    warnings = []

    with pytest.raises(_StreamInterrupted, match="peer closed"):
        list(_iter_stream_resilient(stream, warnings.append))

    assert any("upstream closed" in w for w in warnings)


def test_stall_before_first_event_waits_indefinitely():
    """Before the first event, we rely on httpx read timeout, not inter-chunk.
    Verify that the generator does NOT timeout quickly if no first event arrives
    (it would wait for httpx's read timeout instead)."""
    stream = StallingStream(events_before_stall=0)

    result = []
    timeout_fired = threading.Event()

    def _consumer():
        try:
            # A deliberately tiny inter-chunk deadline: if it were (wrongly)
            # applied before the first event, it would fire almost instantly.
            for ev in _iter_stream_resilient(
                stream, _noop_warn, inter_chunk_timeout_s=0.2,
            ):
                result.append(ev)
        except _StreamInterrupted:
            timeout_fired.set()

    t = threading.Thread(target=_consumer, daemon=True)
    t.start()
    # Wait 1s (5x the inter-chunk deadline) — it must NOT have fired
    t.join(timeout=1)
    assert not timeout_fired.is_set(), "Should not timeout before first event"
    stream.unstall()
    t.join(timeout=3)
