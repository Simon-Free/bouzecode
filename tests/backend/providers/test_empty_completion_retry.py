# [desc] Tests that OpenRouter backend retries degenerate empty completions and surfaces valid responses unchanged
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that OpenRouter backend retries degenerate empty completions and surfaces valid responses unchanged</param></tool_use> [/desc]
"""Repro of the deepseek-v4-pro 'empty turn' bug (2026-06-10): some upstream
providers return a single chunk with empty content, no reasoning, no tool_calls,
finish_reason 'stop'. The backend must re-issue the request instead of handing
the agent loop an empty AssistantTurn (which bounced the session to a premature
conformity close)."""
import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn, TextChunk

EMPTY_SSE = (
    'data: {"id":"gen-1","object":"chat.completion.chunk","model":"deepseek/x",'
    '"choices":[{"index":0,"delta":{"content":"","role":"assistant"},'
    '"finish_reason":"stop","native_finish_reason":"stop"}]}'
)
GOOD_SSE = (
    'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":100,"completion_tokens":10}}'
)
REASONING_ONLY_SSE = (
    'data: {"choices":[{"delta":{"reasoning":"hmm"},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":100,"completion_tokens":3}}'
)


class FakeResponse:
    ok = True
    status_code = 200
    encoding = "utf-8"
    text = ""

    def __init__(self, sse_lines):
        self._sse_lines = sse_lines

    def iter_lines(self, decode_unicode=False):
        yield from self._sse_lines
        yield "data: [DONE]"


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.post_count = 0

    def post(self, url, **kwargs):
        self.post_count += 1
        return FakeResponse(self._responses.pop(0))


@pytest.fixture
def make_session(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")

    def _make(responses):
        session = FakeSession(responses)
        monkeypatch.setattr(
            "bouzecode.backend.agent.providers.backends.openrouter_stream._build_session",
            lambda: session,
        )
        return session

    return _make


def _run():
    from bouzecode.backend.agent.providers.backends.openrouter_stream import stream_openrouter
    return list(stream_openrouter(
        api_key="sk-or-fake", model="deepseek-v4-flash", system="",
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[], config={},
    ))


def _final_turn(events) -> AssistantTurn:
    return next(e for e in events if isinstance(e, AssistantTurn))


def test_empty_completion_is_retried_then_succeeds(make_session):
    session = make_session([[EMPTY_SSE], [GOOD_SSE]])
    events = _run()
    assert session.post_count == 2
    assert any(isinstance(e, TextChunk) for e in events)
    assert _final_turn(events).text == "Hello"


def test_gives_up_after_retry_budget(make_session):
    session = make_session([[EMPTY_SSE], [EMPTY_SSE], [EMPTY_SSE]])
    events = _run()
    assert session.post_count == 3  # 1 attempt + 2 retries, then surface as-is
    turn = _final_turn(events)
    assert turn.text == "" and turn.tool_calls == []
    assert turn.stop_reason == "stop"


def test_substantive_response_is_not_retried(make_session):
    session = make_session([[GOOD_SSE]])
    events = _run()
    assert session.post_count == 1
    assert _final_turn(events).text == "Hello"


def test_reasoning_only_response_is_not_retried(make_session):
    """A turn with reasoning but no content/tools is NOT a provider glitch:
    retrying would discard paid-for reasoning; the agent loop's bounce handles it."""
    session = make_session([[REASONING_ONLY_SSE]])
    events = _run()
    assert session.post_count == 1
    assert _final_turn(events).text == ""
