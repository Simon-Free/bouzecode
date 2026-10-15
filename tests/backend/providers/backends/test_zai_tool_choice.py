"""Z.AI (glm-*) rejects any forced tool_choice with HTTP 400 "Tool choice must be auto".

Real symptom reported by a user on glm-5.3 (z-ai/glm-5.3 via OpenRouter): every
enforcement recovery call ("Enforcement: requesting Methodology..." / "Snippet...")
died with

    OpenRouter request failed: HTTP 400
    {"error":{"message":"Tool choice must be auto","code":400,
              "metadata":{"provider_name":"Z.AI"}}}

so enforcement is completely inoperative on that model. The forced choice comes from
enforcement_call._ask_forced, which sets config["_tool_choice"] to either
{"type":"function","function":{"name":<tool>}} (Methodology) or "required" (Snippet);
openrouter_stream then copies it straight into the request body. Z.AI accepts only
"auto". The recovery system prompt already names the single tool to call and forbids
anything else, so degrading to "auto" keeps the call functional.
"""
from bouzecode.backend.agent.providers.backends import openrouter_stream as ors

FORCED_METHODOLOGY = {"type": "function", "function": {"name": "Methodology"}}


class _FakeResp:
    """Minimal stand-in for requests.Response as consumed by post_with_retry + iter_sse."""

    ok = True
    status_code = 200
    text = ""

    def __init__(self, lines):
        self._lines = lines
        self.encoding = None

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def close(self):
        pass


class _FakeSession:
    """Captures the JSON body actually POSTed to /chat/completions."""

    def __init__(self):
        self.payloads = []

    def post(self, url, headers=None, json=None, **kwargs):
        self.payloads.append(json)
        if len(self.payloads) > 2:  # stream_openrouter replays the POST if nothing streamed
            raise AssertionError("fake session POSTed too many times (replay loop)")
        return _FakeResp([
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            'data: [DONE]',
        ])


def _drive(model, config):
    """Run one full stream (glm-5.2: a registered Z.AI alias, routed to OpenRouter) against a fake session and return the body it sent."""
    session = _FakeSession()
    schemas = [{
        "name": "Methodology",
        "description": "persist the note",
        "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}},
    }]
    list(ors.stream_openrouter(
        api_key="k",
        model=model,
        system="SYS",
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=schemas,
        config=config,
        session_factory=lambda: session,
    ))
    assert session.payloads, "no request was sent"
    return session.payloads[0]


def test_glm_forced_function_is_degraded_to_auto():
    """The exact body that crashed the user: forced Methodology on glm-5.3."""
    body = _drive("glm-5.2", {"_tool_choice": FORCED_METHODOLOGY})
    assert body["tool_choice"] == "auto", (
        f"Z.AI refuses a forced tool_choice; body carried {body['tool_choice']!r}"
    )


def test_glm_required_is_degraded_to_auto():
    """recover_snippets uses tool_choice='required' — Z.AI refuses it too."""
    body = _drive("glm-5.2", {"_tool_choice": "required"})
    assert body["tool_choice"] == "auto"


def test_glm_tools_are_still_offered():
    """Degrading the choice must not stop offering the single recovery tool."""
    body = _drive("glm-5.2", {"_tool_choice": FORCED_METHODOLOGY})
    names = [t["function"]["name"] for t in body["tools"]]
    assert names == ["Methodology"]


def test_resolve_tool_choice_degrades_zai_models():
    """Pure helper: alias and resolved OpenRouter id are both covered."""
    for model in ("glm-5.3", "z-ai/glm-5.3", "GLM-4.6"):
        assert ors.resolve_tool_choice(model, {"_tool_choice": FORCED_METHODOLOGY}) == "auto"
        assert ors.resolve_tool_choice(model, {"_tool_choice": "required"}) == "auto"


def test_resolve_tool_choice_keeps_forced_choice_for_other_providers():
    """No behaviour change for models that honour a forced tool_choice."""
    assert ors.resolve_tool_choice(
        "anthropic/claude-sonnet-4", {"_tool_choice": FORCED_METHODOLOGY},
    ) == FORCED_METHODOLOGY
    assert ors.resolve_tool_choice(
        "openai/gpt-4o", {"_tool_choice": "required"},
    ) == "required"


def test_resolve_tool_choice_defaults_to_auto():
    """No _tool_choice in config -> plain "auto", as before."""
    assert ors.resolve_tool_choice("glm-5.3", {}) == "auto"
    assert ors.resolve_tool_choice("openai/gpt-4o", {}) == "auto"
