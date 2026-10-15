# [desc] Tests the HTTP payload + native serialization for gateway_preprod (reasoning, budget floor, tool_call pairing). [/desc]
"""Payload shape and native message serialization for the internal LLM gateway preprod."""
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


def _capture_payload(monkeypatch, model, env_key, transport_attr, config):
    monkeypatch.setenv(env_key, "k-fake")
    session = _FakeSession()
    monkeypatch.setattr(
        f"bouzecode.backend.agent.providers.backends.{transport_attr}",
        lambda: session,
    )
    gen = stream(model=model, system="", messages=[{"role": "user", "content": "Hi"}],
                 tool_schemas=[], config=config)
    list(gen)
    return session.payload


# --- the OpenRouter-only `reasoning` param must not reach the gateway ---

def test_gateway_preprod_omits_reasoning_param(monkeypatch):
    payload = _capture_payload(
        monkeypatch, "gpt-5.5", "OPENAI_API_KEY_PP",
        "openrouter_transport.build_plain_session",
        {"thinking_mode": "extended"},
    )
    # Azure/LiteLLM rejects `reasoning` with HTTP 400 — it must be absent.
    assert "reasoning" not in payload


def test_openrouter_keeps_reasoning_param(monkeypatch):
    # Shipped gate: the OpenRouter `reasoning` param is emitted iff
    # config["native_reasoning"] is truthy (openrouter_stream.stream_openrouter
    # L107), not on the legacy "thinking_mode" key.
    payload = _capture_payload(
        monkeypatch, "deepseek-v4-flash", "OPENROUTER_KEY",
        "openrouter_stream._build_session",
        {"native_reasoning": True},
    )
    assert payload.get("reasoning") == {"enabled": True}


# --- GPT-5 reasoning models: token-budget floor + reasoning_effort ---

def _gateway_gpt5_payload(monkeypatch, config):
    return _capture_payload(
        monkeypatch, "gpt-5.5", "OPENAI_API_KEY_PP",
        "openrouter_transport.build_plain_session", config,
    )


def test_gpt5_small_budget_is_floored_to_6000(monkeypatch):
    # A side-call-sized budget (1024) would be entirely consumed by reasoning,
    # returning empty content. The gateway branch floors it so the answer fits.
    payload = _gateway_gpt5_payload(monkeypatch, {"max_tokens": 1024})
    assert payload["max_tokens"] == 6000


def test_gpt5_large_budget_is_kept(monkeypatch):
    payload = _gateway_gpt5_payload(monkeypatch, {"max_tokens": 64000})
    assert payload["max_tokens"] == 64000


def test_gpt5_sends_reasoning_effort_high(monkeypatch):
    payload = _gateway_gpt5_payload(monkeypatch, {"max_tokens": 64000})
    assert payload.get("reasoning_effort") == "high"


def test_non_gpt5_gateway_model_has_no_reasoning_effort_or_floor(monkeypatch):
    # Mistral/Gemini on the gateway aren't GPT-5 reasoning models: no effort param,
    # no budget floor (reasoning_effort would 400 on a non-OpenAI model).
    payload = _capture_payload(
        monkeypatch, "mistral-medium-3-5", "OPENAI_API_KEY_PP",
        "openrouter_transport.build_plain_session", {"max_tokens": 1024},
    )
    assert "reasoning_effort" not in payload
    assert payload["max_tokens"] == 1024


# --- native serialization: orphan tool_results must pair with a tool_call ---

def test_orphan_tool_results_get_synthesized_tool_calls():
    """The minimal-wire drops the assistant-with-tool_calls and keeps only the
    results (a '.' stub leads). The native conversion must synthesize matching
    tool_calls so OpenAI/Azure don't reject 'No tool call found for ... call_id'."""
    from bouzecode.backend.agent.providers.backends.openrouter_native import (
        messages_to_openai_native,
    )
    wire = [
        {"role": "assistant", "content": "."},
        {"role": "tool", "tool_call_id": "call_A", "name": "Glob", "content": "x"},
        {"role": "tool", "tool_call_id": "call_B", "name": "Grep", "content": "y"},
    ]
    out = messages_to_openai_native(wire, system="SYS")
    asst = next(m for m in out if m["role"] == "assistant" and m.get("tool_calls"))
    assert {tc["id"] for tc in asst["tool_calls"]} == {"call_A", "call_B"}
    assert {tc["function"]["name"] for tc in asst["tool_calls"]} == {"Glob", "Grep"}
    declared = {tc["id"] for m in out if m["role"] == "assistant"
                for tc in m.get("tool_calls", [])}
    for m in out:
        if m["role"] == "tool":
            assert m["tool_call_id"] in declared


def test_explicit_tool_calls_are_not_double_synthesized():
    from bouzecode.backend.agent.providers.backends.openrouter_native import (
        messages_to_openai_native,
    )
    wire = [
        {"role": "assistant", "content": "hi",
         "tool_calls": [{"id": "call_A", "name": "Glob", "input": {"pattern": "*"}}]},
        {"role": "tool", "tool_call_id": "call_A", "name": "Glob", "content": "x"},
    ]
    out = messages_to_openai_native(wire, system="SYS")
    asst = next(m for m in out if m["role"] == "assistant" and m.get("tool_calls"))
    assert len(asst["tool_calls"]) == 1
    assert asst["tool_calls"][0]["function"]["arguments"] == '{"pattern": "*"}'
