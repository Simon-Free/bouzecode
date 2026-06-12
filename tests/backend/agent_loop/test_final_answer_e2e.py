# [desc] Tests that FinalAnswer tool properly closes sessions, handles refused closes, and rejects empty answers. [/desc]
"""FinalAnswer(answer=...) ends the session via ends_turn (positive close act,
no more ambiguity with empty replies). On native models a one-call validator
checks the Methodology todolist and can refuse the close (validate_close is
monkeypatched here; its own logic is unit-tested in agent/test_close_validator)."""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">[x] tout fait</param></tool_use>'
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         '<param name="answer">Fichiers créés, 2 tests verts.</param></tool_use>')


def _users(result):
    return [str(m.get("content", "")) for m in result.messages if m.get("role") == "user"]


def test_final_answer_closes_the_session():
    mock = MockLLM([f"{METH}\n{FINAL}", "JAMAIS CONSOMMÉ"])
    result = bouzecode(["fais le travail"], mock_llm=mock)
    assert result.state.final_answer == "Fichiers créés, 2 tests verts."
    asst = [m for m in result.messages if m.get("role") == "assistant"]
    assert not any("JAMAIS CONSOMMÉ" in str(m.get("content", "")) for m in asst)


def test_refused_close_keeps_session_running(monkeypatch):
    verdicts = iter([(False, "la commande de validation n'a pas été exécutée"), (True, "")])
    monkeypatch.setattr(
        "bouzecode.backend.agent.close_validator.validate_close",
        lambda answer, config: next(verdicts),
    )
    bash = '<tool_use name="Bash" id="b1"><param name="command">echo run-tests</param></tool_use>'
    mock = MockLLM([
        f"{METH}\n{FINAL}",          # close attempt -> refused by validator
        f"{METH}\n{bash}",           # model finishes the missing work
        f"{METH}\n{FINAL}",          # second close attempt -> accepted
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock)
    assert result.state.final_answer == "Fichiers créés, 2 tests verts."
    transcript = " ".join(str(m.get("content", "")) for m in result.messages)
    assert "CLÔTURE REFUSÉE" in transcript


def test_empty_answer_does_not_close():
    empty_final = '<tool_use name="FinalAnswer" id="f1"><param name="answer"> </param></tool_use>'
    mock = MockLLM([f"{METH}\n{empty_final}", f"fini.\n{METH}"])
    result = bouzecode(["fais le travail"], mock_llm=mock)
    assert result.state.final_answer == ""
    assert "fini" in result.last_reply
