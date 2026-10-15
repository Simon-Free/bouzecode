# [desc] Pytest verifying gateway PROD gpt-5.6-* payload: no reasoning param, GPT-5 budget floored to 6000, reasoning_effort=high. [/desc]
"""Payload shape for the internal LLM gateway PROD OpenAI-compat models (gpt-5.6-*).

Mirrors gateway preprod: the OpenRouter-only `reasoning` param must not reach the
gateway; GPT-5 reasoning models get a 6000-token budget floor + reasoning_effort=high.
"""
import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream


class _FakeResponse:
    ok = True
    status_code = 200
    encoding = "utf-8"
    text = ""

    def iter_lines(self, decode_unicode=False):
        yield ('data: {"choices":[{"delta":{"content":"OK"},'
               '"finish_reason":"stop"}],"usage":{"prompt_tokens":5,'
               '"completion_tokens":1}}')
        yield "data: [DONE]"


class _FakeSession:
    def __init__(self):
        self.payload = None

    def post(self, url, **kwargs):
        self.payload = kwargs.get("json")
        return _FakeResponse()


def _capture_payload(monkeypatch, model, config):
    # gateway_openai auth = get_api_key → ANTHROPIC_AUTH_TOKEN.
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-prod-fake")
    session = _FakeSession()
    monkeypatch.setattr(
        "bouzecode.backend.agent.providers.backends."
        "openrouter_transport.build_plain_session",
        lambda: session,
    )
    gen = stream(model=model, system="", messages=[{"role": "user", "content": "Hi"}],
                 tool_schemas=[], config=config)
    list(gen)
    return session.payload


def test_gateway_openai_omits_reasoning_param(monkeypatch):
    # Azure/LiteLLM rejects `reasoning` with HTTP 400 — it must be absent.
    payload = _capture_payload(monkeypatch, "gpt-5.6-sol", {"thinking_mode": "extended"})
    assert "reasoning" not in payload


def test_gpt5_small_budget_is_floored_to_6000(monkeypatch):
    payload = _capture_payload(monkeypatch, "gpt-5.6-sol", {"max_tokens": 1024})
    assert payload["max_tokens"] == 6000


def test_gpt5_large_budget_is_kept(monkeypatch):
    payload = _capture_payload(monkeypatch, "gpt-5.6-sol", {"max_tokens": 64000})
    assert payload["max_tokens"] == 64000


def test_gpt5_sends_reasoning_effort_high(monkeypatch):
    payload = _capture_payload(monkeypatch, "gpt-5.6-terra", {"max_tokens": 64000})
    assert payload.get("reasoning_effort") == "high"
