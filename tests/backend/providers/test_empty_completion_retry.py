# [desc] The OpenRouter backend retries degenerate empty completions (provider glitch) transparently. [/desc]
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
# Mesuré sur un run reel (2026-09-28) : "+2 out" avec un contenu reduit a du
# whitespace. C'est la MEME degenerescence qu'un content vide (le tour est vide
# cote boucle d'agent, text.strip() == ""), mais l'ancienne condition
# `if text or ...` le prenait pour une reponse substantielle et ne retryait pas.
WHITESPACE_SSE = (
    'data: {"choices":[{"delta":{"content":"  ","role":"assistant"},'
    '"finish_reason":"stop","native_finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":100,"completion_tokens":2}}'
)
# Refus de contenu : deterministe, rejouer la requete redonnera un refus.
CONTENT_FILTER_SSE = (
    'data: {"choices":[{"delta":{"content":"","role":"assistant"},'
    '"finish_reason":"content_filter","native_finish_reason":"content_filter"}],'
    '"usage":{"prompt_tokens":100,"completion_tokens":0}}'
)
REFUSAL_SSE = (
    'data: {"choices":[{"delta":{"refusal":"I cannot help with that.",'
    '"role":"assistant"},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":100,"completion_tokens":2}}'
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
def make_session(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    monkeypatch.setattr(
        "bouzecode.backend.agent.providers.backends.completion_diagnostics.DIAGNOSTICS_DIR",
        tmp_path / "diagnostics")

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


def test_whitespace_only_completion_is_retried(make_session):
    """Un contenu reduit a du whitespace est une completion degeneree, pas une
    reponse : la boucle d'agent la verra vide (text.strip() == ""), donc le backend
    doit la rejouer comme un content vide."""
    session = make_session([[WHITESPACE_SSE], [GOOD_SSE]])
    events = _run()
    assert session.post_count == 2
    assert _final_turn(events).text == "Hello"


def test_content_filter_is_not_retried_and_is_reported(make_session):
    """Un refus content_filter n'est jamais rejoue a l'identique (deterministe, voir
    test_gateway_content_filter), ni avec le budget des completions vides : il remonte
    tel quel pour que la boucle le rejoue avec la note compactee puis sur la chaine
    de repli, ou close sur 'content_refusal' au lieu du generique 'empty_completion'."""
    session = make_session([[CONTENT_FILTER_SSE]] * 3)
    events = _run()
    assert session.post_count == 1
    turn = _final_turn(events)
    assert turn.stop_reason == "content_filter"
    assert turn.refusal


def test_explicit_refusal_field_is_not_retried_and_is_reported(make_session):
    """Champ `refusal` du delta (OpenAI) : meme verdict, avec le texte du refus."""
    session = make_session([[REFUSAL_SSE]])
    events = _run()
    assert session.post_count == 1
    turn = _final_turn(events)
    assert turn.refusal == "I cannot help with that."
    assert turn.stop_reason == "content_filter"


def test_reasoning_only_response_is_not_retried(make_session):
    """A turn with reasoning but no content/tools is NOT a provider glitch:
    retrying would discard paid-for reasoning; the agent loop's bounce handles it."""
    session = make_session([[REASONING_ONLY_SSE]])
    events = _run()
    assert session.post_count == 1
    assert _final_turn(events).text == ""
