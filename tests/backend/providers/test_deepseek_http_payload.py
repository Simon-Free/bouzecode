# [desc] Diagnostic test capturing the HTTP payload sent to OpenRouter to verify Methodology/Snippet tools are present.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Diagnostic test capturing the HTTP payload sent to OpenRouter to verify Methodology/Snippet tools are present.</param></tool_use> [/desc]
"""Capture the actual HTTP payload sent to OpenRouter to confirm tools are present."""
import json
import pytest

from bouzecode.backend.tools.schemas import TOOL_SCHEMAS


class FakeResponse:
    ok = True
    status_code = 200
    encoding = "utf-8"
    text = ""

    def iter_lines(self, decode_unicode=False):
        # Return a single SSE chunk with finish_reason to end the stream cleanly
        yield 'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":10}}'
        yield "data: [DONE]"


class FakeSession:
    def __init__(self):
        self.captured_payload = None
        self.captured_headers = None

    def post(self, url, **kwargs):
        self.captured_payload = kwargs.get("json")
        self.captured_headers = kwargs.get("headers")
        return FakeResponse()


@pytest.fixture
def capture_session(monkeypatch):
    """Patch _build_session to capture the HTTP payload."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    # Disable NTLM proxy
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    session = FakeSession()
    monkeypatch.setattr(
        "bouzecode.backend.agent.providers.backends.openrouter_stream._build_session",
        lambda: session,
    )
    return session


def _run_stream(config=None):
    """Run the full dispatch stream and consume all events."""
    from bouzecode.backend.agent.providers.backends.dispatch import stream

    config = config or {}
    gen = stream(
        model="deepseek-v4-flash",
        system="",
        messages=[{"role": "user", "content": "Hello, test diagnostic."}],
        tool_schemas=TOOL_SCHEMAS,
        config=config,
    )
    events = list(gen)
    return events


class TestDeepSeekHttpPayload:
    """Verify the actual HTTP body sent to OpenRouter for DeepSeek."""

    def test_payload_has_tools_key(self, capture_session):
        _run_stream()
        payload = capture_session.captured_payload
        assert payload is not None, "No HTTP request was captured"
        assert "tools" in payload, (
            f"'tools' key missing from payload. Keys: {list(payload.keys())}"
        )

    def test_tools_contains_methodology(self, capture_session):
        _run_stream()
        tools = capture_session.captured_payload["tools"]
        names = [t["function"]["name"] for t in tools]
        assert "Methodology" in names, f"Methodology not in tools: {names}"

    def test_tools_contains_snippet(self, capture_session):
        _run_stream()
        tools = capture_session.captured_payload["tools"]
        names = [t["function"]["name"] for t in tools]
        assert "Snippet" in names, f"Snippet not in tools: {names}"

    def test_methodology_has_detailed_description(self, capture_session):
        _run_stream()
        tools = capture_session.captured_payload["tools"]
        meth = next(t for t in tools if t["function"]["name"] == "Methodology")
        desc = meth["function"]["description"]
        # Must explain what it does
        assert len(desc) > 100, f"Description too short ({len(desc)} chars): {desc}"
        assert "WORKING MEMORY" in desc or "working memory" in desc.lower()

    def test_system_message_contains_methodology_instructions(self, capture_session):
        _run_stream()
        messages = capture_session.captured_payload["messages"]
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        content = system_msg["content"]
        # The system prompt should contain the methodology instructions
        assert "Methodology" in content, "System message doesn't mention Methodology"
        assert "Snippet" in content, "System message doesn't mention Snippet"
        # The MANDATORY every-turn instruction (V2 wording, dc56090)
        assert "à chaque tour" in content

    def test_tool_choice_is_auto(self, capture_session):
        _run_stream()
        payload = capture_session.captured_payload
        assert payload.get("tool_choice") == "auto"

    def test_print_payload_summary(self, capture_session, capsys):
        """Print a diagnostic summary of what DeepSeek receives."""
        _run_stream()
        payload = capture_session.captured_payload
        print("\n=== DEEPSEEK HTTP PAYLOAD DIAGNOSTIC ===")
        print(f"Keys: {list(payload.keys())}")
        print(f"Model: {payload.get('model')}")
        if "tools" in payload:
            names = [t["function"]["name"] for t in payload["tools"]]
            print(f"Tools ({len(names)}): {names}")
            meth = next((t for t in payload["tools"] if t["function"]["name"] == "Methodology"), None)
            if meth:
                print(f"\nMethodology description ({len(meth['function']['description'])} chars):")
                print(f"  {meth['function']['description'][:200]}...")
                print(f"  Parameters: {list(meth['function']['parameters'].get('properties', {}).keys())}")
        else:
            print("NO TOOLS IN PAYLOAD!")
        msgs = payload.get("messages", [])
        if msgs:
            sys_msg = msgs[0]
            print(f"\nSystem message role: {sys_msg.get('role')}")
            print(f"System message length: {len(sys_msg.get('content', ''))} chars")
            content = sys_msg.get("content", "")
            if "Methodology" in content:
                # Find the methodology instruction
                idx = content.find("Chaque tour émet un Methodology")
                if idx >= 0:
                    print(f"  Found 'Chaque tour émet un Methodology' at char {idx}")
                else:
                    print("  'Chaque tour émet un Methodology' NOT FOUND in system")
        print("=== END DIAGNOSTIC ===")
