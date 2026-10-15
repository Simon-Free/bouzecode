# [desc] 429/529/5xx are retried by OUR loops (SDK max_retries=0), logged per attempt, Retry-After honoured, nothing on stderr. [/desc]
"""Les relances du SDK Anthropic (max_retries=3) absorbaient 429, 529 et 5xx en silence
avant notre boucle. Elles sont coupées : chaque tentative passe par notre boucle, qui
journalise (le journal du process, pas le chat) et respecte Retry-After."""
import json
import logging

import anthropic
import httpx

from bouzecode.backend.agent.providers.backends.anthropic_client import build_anthropic_client
from bouzecode.backend.agent.providers.backends.anthropic_helpers import (
    _create_anthropic_stream_with_retry,
)
from bouzecode.backend.agent.providers.backends.openrouter_retry import post_with_retry

RATE_LIMITED = json.dumps({"type": "error", "error": {"type": "rate_limit_error",
                                                       "message": "slow down"}})
OVERLOADED = json.dumps({"type": "error", "error": {"type": "overloaded_error",
                                                     "message": "Overloaded"}})
EMPTY_STREAM = "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"


class FakeAnthropicServer:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        status, headers, body = self._responses.pop(0)
        return httpx.Response(status, headers=headers, content=body.encode())


def _sdk_client(server) -> anthropic.Anthropic:
    """Même réglage de relances que build_anthropic_client, transport simulé."""
    return anthropic.Anthropic(
        api_key="sk-ant-fake", base_url="https://gateway.example",
        max_retries=build_anthropic_client("sk-ant-fake", "https://gateway.example").max_retries,
        http_client=httpx.Client(transport=httpx.MockTransport(server)))


def test_sdk_client_does_not_retry_by_itself():
    assert build_anthropic_client("sk-ant-fake", "https://gateway.example").max_retries == 0


def test_each_429_and_529_reaches_our_loop_logged_not_printed(caplog, capsys):
    server = FakeAnthropicServer([
        (429, {"content-type": "application/json", "retry-after": "7"}, RATE_LIMITED),
        (529, {"content-type": "application/json"}, OVERLOADED),
        (200, {"content-type": "text/event-stream"}, EMPTY_STREAM),
    ])
    slept = []
    with caplog.at_level(logging.WARNING):
        _create_anthropic_stream_with_retry(
            _sdk_client(server), {"model": "claude-opus-5-5", "max_tokens": 10,
                                  "messages": [{"role": "user", "content": "hi"}]},
            sleep=slept.append, now=lambda: 0.0)
    assert server.requests == 3, "le SDK ne doit plus relancer de son côté"
    assert slept[0] == 7.0, "Retry-After respecté"
    messages = [r.getMessage() for r in caplog.records]
    assert any("Rate limited" in m for m in messages)
    assert any("Server error 529" in m for m in messages)
    assert capsys.readouterr().err == ""


class FakeResponse:
    def __init__(self, status_code: int, headers=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = ""
        self.headers = headers or {}


def test_openrouter_429_is_logged_and_honours_retry_after(caplog, capsys):
    responses = [FakeResponse(429, {"Retry-After": "7"}), FakeResponse(429), FakeResponse(200)]
    slept = []
    with caplog.at_level(logging.WARNING):
        resp = post_with_retry(lambda: responses.pop(0), sleep=slept.append)
    assert resp.ok
    assert slept == [7.0, 4.0]
    assert sum("HTTP 429" in r.getMessage() for r in caplog.records) == 2
    assert capsys.readouterr().err == ""
