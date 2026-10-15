# [desc] Variant A of the Methodology-tax A/B: the hard rule lands at the end of the native system iff the env gate is set. [/desc]
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
    """Le system et ce qui le prolonge hors de la demande. Depuis le 24/09
    (docs/reduction_tokens/correctifs.md §2.2), le system OpenAI ne garde que le préfixe stable
    (les outils, sérialisés après lui, restent en cache) ; contexte et règle finale forment un
    message user à part. Depuis le 2026-10-07, la note est en <working_notes> en tête du
    premier message user (celui de la demande), le message du contexte vient juste après."""
    from bouzecode.backend.agent.providers.backends.dispatch import stream
    list(stream(model="deepseek-v4-flash", system="", tool_schemas=TOOL_SCHEMAS,
                messages=[{"role": "user", "content": "hi"}], config={}))
    contenus = [m["content"] for m in capture_session.captured_payload["messages"]]
    return "\n\n".join(contenus[:1] + contenus[2:])


def test_openrouter_by_default_sends_no_final_rule(capture_session, monkeypatch):
    """A/B DeepSeek du 24/09 (docs/reduction_tokens/correctifs.md §3) : sans la règle finale,
    oublis 15,4 % → 5,8 % à réussite égale. Depuis le retrait du rappel frais (2026-10-05), la
    demande part telle quelle (derrière la note)."""
    monkeypatch.delenv("BOUZECODE_METH_PROMPT_VARIANT", raising=False)
    system = _system_text(capture_session)
    assert "RAPPEL : chaque lot commence par Methodology" not in system
    assert capture_session.captured_payload["messages"][1]["content"].endswith(
        "</working_notes>\n\nhi")


def test_rule_at_end_of_native_system_when_forced(capture_session, monkeypatch):
    """Measured 2026-06-10: 25% -> 11.5% Methodology omissions, 6/6 successes (before the
    fresh reminder existed). Still available with BOUZECODE_METH_PROMPT_VARIANT=A."""
    monkeypatch.setenv("BOUZECODE_METH_PROMPT_VARIANT", "A")
    system = _system_text(capture_session)
    # Audit du prompt (2026-09-24) : la règle est réduite à un rappel d'une ligne, toujours
    # placé en DERNIER (c'est la position que l'A/B a mesurée).
    assert "RAPPEL : chaque lot commence par Methodology" in system
    # The rule must ALWAYS name an explicit close path — without one, the
    # every-turn-Methodology rule forbids the native close signal and caused a
    # 47-turn over-iteration on T100 (2026-06-10).
    assert "FinalAnswer" in system
    assert system.rstrip().endswith("todolist entièrement cochée.")


def test_off_disables_rule_for_baseline_benching(capture_session, monkeypatch):
    monkeypatch.setenv("BOUZECODE_METH_PROMPT_VARIANT", "off")
    system = _system_text(capture_session)
    assert "RAPPEL : chaque lot commence par Methodology" not in system
