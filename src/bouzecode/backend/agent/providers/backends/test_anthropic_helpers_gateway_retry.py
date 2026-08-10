# [desc] Tests: retry of transient Bedrock/LiteLLM 400s vs fatal genuine client 400s in the Anthropic stream helper. [/desc]
"""Une passerelle LLM d'entreprise habille parfois une panne 5xx transitoire de Bedrock
en 400 avec un corps LiteLLM ("BedrockException", "No fallback model group", payload vide {}). Ce 400
doit être REESSAYÉ (comme un InternalServerError), pas tué. Un vrai 400 client (requête
malformée, contexte trop long) doit rester FATAL et remonter immédiatement."""
from __future__ import annotations

import anthropic
import httpx
import pytest

from bouzecode.backend.agent.providers.backends.anthropic_helpers import (
    _create_anthropic_stream_with_retry,
    _TRANSIENT_GATEWAY_MARKERS,
)


def _bad_request(message: str) -> anthropic.BadRequestError:
    """Construit une vraie anthropic.BadRequestError (400) avec un message donné."""
    request = httpx.Request("POST", "https://example.invalid/v1/messages")
    response = httpx.Response(400, request=request)
    return anthropic.BadRequestError(message, response=response, body={})


class _FakeClient:
    """Client dont messages.create lève les erreurs de `errors` dans l'ordre puis réussit."""

    def __init__(self, errors):
        self._errors = list(errors)
        self.calls = 0

        class _Messages:
            def create(inner, **kwargs):  # noqa: N805
                self.calls += 1
                if self._errors:
                    raise self._errors.pop(0)
                return "STREAM_OK"

        self.messages = _Messages()


def test_markers_defined():
    """La constante des marqueurs gateway transitoires doit exister et être non vide."""
    assert _TRANSIENT_GATEWAY_MARKERS
    joined = " ".join(m.lower() for m in _TRANSIENT_GATEWAY_MARKERS)
    assert "bedrockexception" in joined
    assert "no fallback model group" in joined


def test_transient_bedrock_400_is_retried_then_succeeds():
    """Un 400 'BedrockException / No fallback model group' est réessayé puis réussit."""
    transient = _bad_request(
        "litellm.BadRequestError: BedrockException - {}\n"
        "No fallback model group found for original model_group=claude-opus-4-8"
    )
    client = _FakeClient([transient])
    slept: list[float] = []

    result = _create_anthropic_stream_with_retry(
        client, {}, sleep=lambda d: slept.append(d), now=lambda: 0.0,
        warn=lambda m: None,
    )

    assert result == "STREAM_OK"
    assert client.calls == 2  # 1er essai KO (transient) + retry OK
    assert slept  # un backoff a bien eu lieu


def test_genuine_client_400_is_fatal_no_retry():
    """Un vrai 400 client (requête malformée) est RE-levé immédiatement, sans retry."""
    genuine = _bad_request(
        "invalid_request_error: messages: text content blocks must be non-empty"
    )
    client = _FakeClient([genuine, genuine])
    slept: list[float] = []

    with pytest.raises(anthropic.BadRequestError):
        _create_anthropic_stream_with_retry(
            client, {}, sleep=lambda d: slept.append(d), now=lambda: 0.0,
            warn=lambda m: None,
        )

    assert client.calls == 1  # levé au 1er essai
    assert slept == []  # aucun backoff
