"""Claude Opus/Sonnet 5.5, Fable/Mythos 5.1 refuse a forced tool_choice (HTTP 400).

Real symptom (2026-10-05, session 0a3ed5c5, claude-opus-5-5 via the preprod gateway):
every enforcement recovery died with `litellm.BadRequestError: BedrockException ...`.
Only "auto" is accepted; the recovery system prompt names the tool to call.
"""
import pytest

from bouzecode.backend.agent.providers.backends import openrouter_stream as ors
from bouzecode.backend.agent.providers.backends.openrouter_retry import post_with_retry
from bouzecode.backend.agent.providers.backends.tool_choice_policy import (
    refuses_forced_tool_choice, resolve_tool_choice,
)

FORCED = {"type": "function", "function": {"name": "Methodology"}}

AUTO_ONLY = (
    "claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-mythos-5-1",
    "anthropic/claude-opus-5-5", "eu.anthropic.claude-sonnet-5-5-v1:0",
    "us.anthropic.claude-fable-5-1", "bedrock/eu.anthropic.claude-mythos-5-1",
    "Claude-Opus-5-5-20261001", "glm-5.3", "z-ai/glm-5.3",
)
FORCED_OK = (
    "claude-opus-5", "claude-sonnet-5", "claude-opus-4-8", "anthropic/claude-sonnet-4",
    "gpt-5.5", "openai/gpt-4o", "mistral-medium-3-5",
)


@pytest.mark.parametrize("model", AUTO_ONLY)
def test_forced_choice_degrades_to_auto(model):
    assert refuses_forced_tool_choice(model)
    assert resolve_tool_choice(model, {"_tool_choice": FORCED}) == "auto"
    assert resolve_tool_choice(model, {"_tool_choice": "required"}) == "auto"


@pytest.mark.parametrize("model", FORCED_OK)
def test_forced_choice_kept_for_other_models(model):
    assert not refuses_forced_tool_choice(model)
    assert resolve_tool_choice(model, {"_tool_choice": FORCED}) == FORCED
    assert resolve_tool_choice(model, {"_tool_choice": "required"}) == "required"


def test_stream_module_reexports_the_policy():
    assert ors.resolve_tool_choice is resolve_tool_choice


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.ok = status, text, status < 400


def test_error_names_the_provider_label():
    """The gateway reuses the OpenRouter transport: its 400 must not say "OpenRouter"."""
    with pytest.raises(RuntimeError, match=r"^gateway préprod request failed: HTTP 400"):
        post_with_retry(lambda: _Resp(400, "tool_choice"), sleep=lambda _s: None,
                        label="gateway préprod")


def test_error_label_defaults_to_openrouter():
    with pytest.raises(RuntimeError, match=r"^OpenRouter request failed: HTTP 401"):
        post_with_retry(lambda: _Resp(401, "bad key"), sleep=lambda _s: None)


class _SseResp(_Resp):
    encoding = None

    def __init__(self):
        super().__init__(200)

    def iter_lines(self, decode_unicode=False):
        return iter(['data: {"choices":[{"delta":{"content":"ok"}}]}', "data: [DONE]"])

    def close(self):
        pass


class _Session:
    def __init__(self):
        self.payloads = []

    def post(self, url, json=None, **_kw):
        self.payloads.append(json)
        return _SseResp()


def test_gateway_preprod_payload_sends_auto_for_claude_opus_5_5():
    """The exact body that failed: forced Methodology recovery on claude-opus-5-5 (gateway_preprod)."""
    session = _Session()
    schema = {"name": "Methodology", "description": "note",
              "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}}}
    list(ors.stream_openrouter(
        api_key="k", model="claude-opus-5-5", system="SYS",
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[schema],
        config={"_tool_choice": FORCED}, session_factory=lambda: session,
        provider_label="gateway préprod",
    ))
    body = session.payloads[0]
    assert body["tool_choice"] == "auto"
    assert [t["function"]["name"] for t in body["tools"]] == ["Methodology"]
