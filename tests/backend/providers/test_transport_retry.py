"""A network timeout must not abort the turn: the POST is replayed."""
from __future__ import annotations

import pytest
import requests

from bouzecode.backend.agent.providers.backends.openrouter_retry import (
    TRANSPORT_BACKOFFS_S,
    post_with_retry,
    transport_errors,
)


class _Resp:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 400


def _read_timeout():
    return requests.exceptions.ReadTimeout(
        "HTTPSConnectionPool(host='preprod.llm-gateway.example.com', port=443): "
        "Read timed out. (read timeout=10)"
    )


def test_transport_errors_cover_read_timeout():
    assert isinstance(_read_timeout(), transport_errors())


def test_read_timeout_is_retried_then_succeeds():
    calls = []
    slept = []

    def post_once():
        calls.append(1)
        if len(calls) <= 2:
            raise _read_timeout()
        return _Resp()

    resp = post_with_retry(post_once, sleep=slept.append)

    assert resp.ok
    assert len(calls) == 3
    assert slept == list(TRANSPORT_BACKOFFS_S[:2])


def test_connection_error_is_retried():
    calls = []

    def post_once():
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("connection aborted")
        return _Resp()

    assert post_with_retry(post_once, sleep=lambda _s: None).ok
    assert len(calls) == 2


def test_timeout_budget_exhausted_reraises_original_error():
    calls = []

    def post_once():
        calls.append(1)
        raise _read_timeout()

    with pytest.raises(requests.exceptions.ReadTimeout):
        post_with_retry(post_once, sleep=lambda _s: None)

    assert len(calls) == len(TRANSPORT_BACKOFFS_S) + 1


def test_transport_budget_is_independent_from_status_budget():
    """A 429 burst must not consume the timeout budget (and vice versa)."""
    calls = []

    def post_once():
        calls.append(1)
        if len(calls) == 1:
            raise _read_timeout()
        if len(calls) == 2:
            return _Resp(429, "rate limited")
        return _Resp()

    assert post_with_retry(post_once, sleep=lambda _s: None).ok
    assert len(calls) == 3
