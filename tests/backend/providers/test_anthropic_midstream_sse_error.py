# [desc] Anthropic route: an SSE `error` event mid-stream and a 529 on create are retried, through the real SDK. [/desc]
"""Erreurs passagères du fournisseur sur la route Anthropic `/v1/messages`.

Un événement SSE `error` (overloaded_error, rate_limit_error, api_error) reçu APRÈS un
`messages.create` réussi devient dans le SDK un APIStatusError de statut 200 : il tuait
la session (api_error) au lieu d'être rejoué comme une coupure en vol. Et un 529
(OverloadedError) n'hérite pas d'InternalServerError : le create ne le relançait pas.

Le faux serveur est un `httpx.MockTransport` branché sous un VRAI client Anthropic : le
SDK parse réellement les SSE et lève réellement ses exceptions.
"""
import inspect
import json

import anthropic
import httpx
import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn, StreamRestart

MODULE = "bouzecode.backend.agent.providers.backends.anthropic_stream"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


MESSAGE_START = _sse("message_start", {"type": "message_start", "message": {
    "id": "msg_1", "type": "message", "role": "assistant", "content": [],
    "model": "claude-opus-5-5", "stop_reason": None, "stop_sequence": None,
    "usage": {"input_tokens": 100, "output_tokens": 0}}})
GOOD_STREAM = MESSAGE_START + "".join([
    _sse("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
    _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "Bonjour"}}),
    _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
    _sse("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 5}}),
    _sse("message_stop", {"type": "message_stop"}),
])


def _error_stream(error_type: str) -> str:
    return MESSAGE_START + _sse("error", {"type": "error", "error": {
        "type": error_type, "message": "Overloaded"}})


SSE_HEADERS = {"content-type": "text/event-stream"}
OVERLOADED_529 = (529, {"content-type": "application/json"}, json.dumps(
    {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))


class FakeAnthropicServer:
    """Sert les réponses dans l'ordre ; chaque entrée est un corps SSE ou (statut, en-têtes, corps)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        answer = self._responses.pop(0)
        if isinstance(answer, str):
            return httpx.Response(200, headers=SSE_HEADERS, content=answer.encode())
        status, headers, body = answer
        return httpx.Response(status, headers=headers, content=body.encode())


@pytest.fixture
def serve(monkeypatch):
    def _serve(responses):
        server = FakeAnthropicServer(responses)
        client = anthropic.Anthropic(
            api_key="sk-ant-fake", base_url="https://gateway.example", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(server)))
        monkeypatch.setattr(f"{MODULE}.build_anthropic_client",
                            lambda api_key, base_url=None: client)
        return server
    return _serve


def _events() -> list:
    from bouzecode.backend.agent.providers.backends import anthropic_stream
    stream_anthropic = inspect.unwrap(anthropic_stream.stream_anthropic)
    return list(stream_anthropic(
        api_key="sk-ant-fake", model="claude-opus-5-5", system="sys",
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[], config={}))


def _final_turn(events) -> AssistantTurn:
    return next(e for e in events if isinstance(e, AssistantTurn))


@pytest.mark.parametrize("error_type", ["overloaded_error", "rate_limit_error", "api_error"])
def test_sse_error_mid_stream_is_replayed(serve, error_type):
    server = serve([_error_stream(error_type), GOOD_STREAM])
    events = _events()
    assert _final_turn(events).text == "Bonjour"
    assert server.requests == 2
    assert any(isinstance(e, StreamRestart) for e in events)


def test_non_transient_sse_error_still_raises(serve):
    serve([_error_stream("invalid_request_error")])
    with pytest.raises(anthropic.APIStatusError):
        _events()


def test_overloaded_529_on_create_is_retried(serve):
    server = serve([OVERLOADED_529, GOOD_STREAM])
    assert _final_turn(_events()).text == "Bonjour"
    assert server.requests == 2
