# [desc] chat/completions route: an `error` chunk mid-stream is replayed (StreamRestart), then ignored once the budget is spent. [/desc]
"""Un chunk `error` en plein flux (OpenRouter : `error` + finish_reason "error" ; LiteLLM :
`error` seul) arrive après un POST 200. Il était ignoré : le tour restait tronqué ou vide,
sans trace. Il est maintenant rejoué, et le consommateur reçoit StreamRestart s'il avait
déjà vu une partie de la tentative avortée."""
import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn, StreamRestart

MODULE = "bouzecode.backend.agent.providers.backends.openrouter_stream"
PARTIAL_TEXT = 'data: {"choices":[{"delta":{"content":"Bonj"}}]}'
OPENROUTER_ERROR = ('data: {"error":{"code":502,"message":"Provider overloaded"},'
                    '"choices":[{"delta":{"content":""},"finish_reason":"error"}]}')
LITELLM_ERROR = 'data: {"error":{"type":"api_error","message":"upstream reset"}}'
GOOD = ('data: {"choices":[{"delta":{"content":"Bonjour"},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":100,"completion_tokens":10}}')


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


class FakeGateway:
    def __init__(self, responses):
        self._responses = list(responses)
        self.post_count = 0

    def post(self, url, **kwargs):
        self.post_count += 1
        return FakeResponse(self._responses.pop(0))


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(f"{MODULE}._sleep", waited.append)
    return waited


def _events(gateway: FakeGateway) -> list:
    from bouzecode.backend.agent.providers.backends.openrouter_stream import stream_openrouter
    return list(stream_openrouter(
        api_key="k-fake", model="claude-opus-5-5", system="sys",
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[], config={},
        base_url="https://gateway.example/v1", session_factory=lambda: gateway,
        send_reasoning=False, provider_label="gateway preprod",
    ))


def _final_turn(events) -> AssistantTurn:
    return next(e for e in events if isinstance(e, AssistantTurn))


def test_error_chunk_after_text_is_replayed_with_a_restart(sleeps):
    gateway = FakeGateway([[PARTIAL_TEXT, OPENROUTER_ERROR], [GOOD]])
    events = _events(gateway)
    assert gateway.post_count == 2 and sleeps == [2.0]
    assert any(isinstance(e, StreamRestart) for e in events)
    assert _final_turn(events).text == "Bonjour"


def test_litellm_error_chunk_before_any_text_is_replayed(sleeps):
    gateway = FakeGateway([[LITELLM_ERROR], [GOOD]])
    events = _events(gateway)
    assert gateway.post_count == 2
    assert not any(isinstance(e, StreamRestart) for e in events)
    assert _final_turn(events).text == "Bonjour"


def test_budget_spent_keeps_the_partial_turn(sleeps):
    gateway = FakeGateway([[PARTIAL_TEXT, OPENROUTER_ERROR]] * 3)
    turn = _final_turn(_events(gateway))
    assert gateway.post_count == 3 and sleeps == [2.0, 8.0]
    assert turn.text == "Bonj" and turn.stop_reason == "error"
