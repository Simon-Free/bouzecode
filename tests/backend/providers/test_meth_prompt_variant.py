# [desc] Tests that the Methodology hard rule is injected into DeepSeek native system prompt and can be disabled via env var
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that the Methodology hard rule is injected into DeepSeek native system prompt and can be disabled via env var</param></tool_use> [/desc]
import pytest

from bouzecode.backend.tools.schemas import TOOL_SCHEMAS


class FakeResponse:
    ok = True
    status_code = 200
    encoding = "utf-8"
    text = ""

    def iter_lines(self, decode_unicode=False):
        yield 'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}'
        yield "data: [DONE]"


class FakeSession:
    def __init__(self):
        self.captured_payload = None

    def post(self, url, **kwargs):
        self.captured_payload = kwargs.get("json")
        return FakeResponse()


@pytest.fixture
def capture_session(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    session = FakeSession()
    monkeypatch.setattr(
        "bouzecode.backend.agent.providers.backends.openrouter_stream._build_session",
        lambda: session,
    )
    return session


def _system_text(capture_session):
    from bouzecode.backend.agent.providers.backends.dispatch import stream
    list(stream(model="deepseek-v4-flash", system="", tool_schemas=TOOL_SCHEMAS,
                messages=[{"role": "user", "content": "hi"}], config={}))
    return capture_session.captured_payload["messages"][0]["content"]


def test_rule_at_end_of_native_system_by_default(capture_session, monkeypatch):
    """Measured 2026-06-10: 25% -> 11.5% Methodology omissions, 6/6 successes."""
    monkeypatch.delenv("BOUZECODE_METH_PROMPT_VARIANT", raising=False)
    system = _system_text(capture_session)
    assert "RÈGLE FINALE NON NÉGOCIABLE" in system
    # The rule must ALWAYS name an explicit close path — without one, the
    # every-turn-Methodology rule forbids the native close signal and caused a
    # 47-turn over-iteration on T100 (2026-06-10).
    assert "FinalAnswer" in system
    assert system.rstrip().endswith("FinalAnswer immédiat.")


def test_off_disables_rule_for_baseline_benching(capture_session, monkeypatch):
    monkeypatch.setenv("BOUZECODE_METH_PROMPT_VARIANT", "off")
    system = _system_text(capture_session)
    assert "RÈGLE FINALE NON NÉGOCIABLE" not in system
