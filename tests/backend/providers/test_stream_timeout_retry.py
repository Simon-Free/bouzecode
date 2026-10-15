"""A read timeout in the middle of the SSE body must not abort the turn.

The gateway preprod endpoint drops slow connections ("Read timed out. (read
timeout=10)"); before this, the exception escaped stream_openrouter and hit the
REPL catch-all ("Turn aborted due to an unhandled error"). The request is
replayed as long as nothing was streamed to the UI yet.
"""
from __future__ import annotations

import pytest
import requests

from bouzecode.backend.agent.providers.backends import openrouter_stream as mod
from bouzecode.backend.agent.providers.types import AssistantTurn, TextChunk


class _FakeResponse:
    ok = True
    status_code = 200
    encoding = "utf-8"
    text = ""


class _FakeSession:
    def __init__(self):
        self.posts = 0

    def post(self, *args, **kwargs):
        self.posts += 1
        return _FakeResponse()


def _chunk(text=None, finish=None):
    delta = {} if text is None else {"content": text}
    choice = {"delta": delta}
    if finish:
        choice["finish_reason"] = finish
    return {"choices": [choice]}


def _run(monkeypatch, iter_sse_impl):
    """Drive stream_openrouter with a fake transport; return (events, session)."""
    session = _FakeSession()
    slept: list[float] = []
    monkeypatch.setattr(mod, "_build_session", lambda: session)
    monkeypatch.setattr(mod, "_iter_sse", iter_sse_impl)
    monkeypatch.setattr(mod, "_sleep", slept.append)
    monkeypatch.setattr(mod, "model_uses_native_tools", lambda *a, **k: False)
    events = list(mod.stream_openrouter(
        "key", "some/model", "system",
        [{"role": "user", "content": "hi"}], [], {},
    ))
    return events, session, slept


def test_read_timeout_before_any_output_replays_the_request(monkeypatch):
    calls = {"n": 0}

    def iter_sse(resp, watchdog=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.ReadTimeout(
                "HTTPSConnectionPool(host='preprod.llm-gateway.example.com', port=443): "
                "Read timed out. (read timeout=10)"
            )
        yield _chunk("hello ")
        yield _chunk("world", finish="stop")

    events, session, slept = _run(monkeypatch, iter_sse)

    turn = events[-1]
    assert isinstance(turn, AssistantTurn)
    assert turn.text == "hello world"
    assert session.posts == 2, "the POST must be replayed after the timeout"
    assert slept == [2.0], "first transport backoff applied"
    # No duplicated text reached the UI.
    assert "".join(e.text for e in events if isinstance(e, TextChunk)) == "hello world"


def test_cut_after_text_is_replayed_with_stream_restart(monkeypatch):
    """Session 9d81964e (2026-10-06) : ChunkedEncodingError après du texte = process tué.
    Rejoué désormais ; StreamRestart fait jeter au consommateur la tentative avortée."""
    from bouzecode.backend.agent.providers.types import StreamRestart
    calls = {"n": 0}

    def iter_sse(resp, watchdog=None):
        calls["n"] += 1
        if calls["n"] == 1:
            yield _chunk("partial answer")
            raise requests.exceptions.ChunkedEncodingError("Response ended prematurely")
        yield _chunk("full answer", finish="stop")

    events, session, slept = _run(monkeypatch, iter_sse)
    assert any(isinstance(e, StreamRestart) for e in events)
    assert events[-1].text == "full answer"
    assert session.posts == 2 and slept == [mod._STREAM_ERROR_BACKOFFS_S[0]]


def test_cut_after_text_raises_once_the_budget_is_spent(monkeypatch):
    calls = {"n": 0}

    def iter_sse(resp, watchdog=None):
        calls["n"] += 1
        yield _chunk("partial answer")
        raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)")

    with pytest.raises(requests.exceptions.ReadTimeout):
        _run(monkeypatch, iter_sse)
    assert calls["n"] == 1 + len(mod._STREAM_ERROR_BACKOFFS_S)


def test_timeout_budget_is_bounded(monkeypatch):
    def iter_sse(resp, watchdog=None):
        raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)")
        yield  # pragma: no cover - generator marker

    with pytest.raises(requests.exceptions.ReadTimeout):
        _run(monkeypatch, iter_sse)


def test_empty_completion_retry_still_works(monkeypatch):
    """The rewritten loop must keep the pre-existing empty-completion budget."""
    calls = {"n": 0}

    def iter_sse(resp, watchdog=None):
        calls["n"] += 1
        if calls["n"] <= mod._EMPTY_COMPLETION_RETRIES:
            yield _chunk(finish="stop")
            return
        yield _chunk("finally", finish="stop")

    events, session, _ = _run(monkeypatch, iter_sse)
    assert events[-1].text == "finally"
    assert session.posts == mod._EMPTY_COMPLETION_RETRIES + 1
