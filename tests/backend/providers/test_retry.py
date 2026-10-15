# [desc] Tests retry logic for Anthropic API stream creation with rate limiting, budgets, and error handling. [/desc]
"""Tests for _create_anthropic_stream_with_retry (providers.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic

from bouzecode.backend.agent.providers.backends.anthropic_helpers import _create_anthropic_stream_with_retry


class FakeRateLimit(anthropic.RateLimitError):
    """Cheap subclass that skips the real SDK __init__ (which needs an httpx Response)."""
    def __init__(self):
        Exception.__init__(self, "fake rate limit")


class _Messages:
    def __init__(self, raise_times: int, outcome):
        self._raise_times = raise_times
        self._outcome = outcome
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        if self.call_count <= self._raise_times:
            raise FakeRateLimit()
        return self._outcome


class _FakeClient:
    def __init__(self, raise_times: int, outcome):
        self.messages = _Messages(raise_times, outcome)


def _instrumented_clock():
    """Return (now_fn, sleep_fn, sleeps) that advances a fake clock on each sleep."""
    current = [0.0]
    sleeps: list[float] = []

    def now() -> float:
        return current[0]

    def sleep(duration: float) -> None:
        sleeps.append(duration)
        current[0] += duration

    return now, sleep, sleeps


def test_returns_immediately_when_no_rate_limit():
    sentinel = object()
    client = _FakeClient(raise_times=0, outcome=sentinel)
    warnings: list[str] = []
    now, sleep, sleeps = _instrumented_clock()

    result = _create_anthropic_stream_with_retry(
        client, {"model": "x"},
        sleep=sleep, now=now, warn=warnings.append,
    )

    assert result is sentinel
    assert client.messages.call_count == 1
    assert sleeps == []
    assert warnings == []


def test_retries_until_success():
    sentinel = object()
    client = _FakeClient(raise_times=3, outcome=sentinel)
    warnings: list[str] = []
    now, sleep, sleeps = _instrumented_clock()

    result = _create_anthropic_stream_with_retry(
        client, {"model": "x"},
        interval_s=3.0, budget_s=300.0,
        sleep=sleep, now=now, warn=warnings.append,
    )

    assert result is sentinel
    assert client.messages.call_count == 4
    # Progressive (exponential) backoff on 429: 3s, 6s, 12s.
    assert sleeps == [3.0, 6.0, 12.0]
    assert len(warnings) == 3
    assert "Rate limited" in warnings[0]


def test_backoff_is_capped_at_max_delay():
    sentinel = object()
    client = _FakeClient(raise_times=6, outcome=sentinel)
    now, sleep, sleeps = _instrumented_clock()

    _create_anthropic_stream_with_retry(
        client, {"model": "x"},
        interval_s=3.0, budget_s=1000.0,
        sleep=sleep, now=now, warn=lambda _m: None,
    )

    assert sleeps == [3.0, 6.0, 12.0, 24.0, 30.0, 30.0]


def test_honors_retry_after_header():
    class _Resp:
        headers = {"retry-after": "7"}

    class _RateLimitWithHeader(anthropic.RateLimitError):
        def __init__(self):
            Exception.__init__(self, "rate limit with retry-after")
            self.response = _Resp()

    class _Msgs:
        call_count = 0

        def create(self, **_kwargs):
            self.call_count += 1
            if self.call_count == 1:
                raise _RateLimitWithHeader()
            return "ok"

    class _Client:
        messages = _Msgs()

    now, sleep, sleeps = _instrumented_clock()
    result = _create_anthropic_stream_with_retry(
        _Client(), {"model": "x"},
        interval_s=3.0, budget_s=300.0,
        sleep=sleep, now=now, warn=lambda _m: None,
    )

    assert result == "ok"
    assert sleeps == [7.0]


def test_raises_after_budget_exceeded():
    client = _FakeClient(raise_times=10_000, outcome=None)
    now, sleep, _sleeps = _instrumented_clock()

    with pytest.raises(anthropic.RateLimitError):
        _create_anthropic_stream_with_retry(
            client, {"model": "x"},
            interval_s=3.0, budget_s=9.0,
            sleep=sleep, now=now, warn=lambda _m: None,
        )

    # Backoff 3s then 6s (capped to remaining budget); 3rd attempt sees elapsed=9 and re-raises.
    assert client.messages.call_count == 3
    assert _sleeps == [3.0, 6.0]


def test_other_exceptions_not_retried():
    class _BadClient:
        class messages:
            call_count = 0
            @classmethod
            def create(cls, **_kwargs):
                cls.call_count += 1
                raise ValueError("unrelated")

    now, sleep, _sleeps = _instrumented_clock()
    with pytest.raises(ValueError):
        _create_anthropic_stream_with_retry(
            _BadClient(), {"model": "x"},
            sleep=sleep, now=now, warn=lambda _m: None,
        )
    assert _BadClient.messages.call_count == 1
