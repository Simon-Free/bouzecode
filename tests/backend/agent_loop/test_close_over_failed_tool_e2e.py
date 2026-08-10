# [desc] Conversation tests: a FinalAnswer emitted alongside a tool the harness refused does not close the session. [/desc]
"""Closing on a tool that never ran ships a conclusion built on nothing.

A session closes only on a close act the turn actually SUPPORTS. When the model
fires FinalAnswer in the same batch as a tool the harness REFUSED (unknown tool,
bad params, denied write, XML parse error…), its answer rests on a result it never
obtained — so the loop spends a turn naming the failure instead of closing.

The line is deliberately narrow: a tool that RAN and reported bad news (pytest with
failing tests, a non-zero exit code) did its job. Blocking there would make it
impossible for an agent to ever deliver "the tests fail because X".

No `mock_tools` here on purpose: the point is what the REAL registry does with a
tool it refuses, and `mock_tools` fakes every tool (FinalAnswer included).
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
ANSWER = "Tout est vérifié, 3 tests verts."
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         f'<param name="answer">{ANSWER}</param></tool_use>')
# An unknown tool: the registry refuses it with "Error: ..." without executing it.
GHOST = '<tool_use name="NoSuchTool" id="g1"><param name="x">1</param></tool_use>'
BASH_OK = '<tool_use name="Bash" id="b1"><param name="command">echo ok</param></tool_use>'


def _users(result):
    return [str(m.get("content", "")) for m in result.messages if m.get("role") == "user"]


def _refusal_notices(result):
    return [m for m in _users(result) if "ta clôture n'a PAS été acceptée" in m]


def test_final_answer_beside_a_refused_tool_does_not_close():
    """The session keeps running and the model is told WHICH tool failed and why."""
    mock = MockLLM([
        f"{METH}\n{GHOST}\n{FINAL}",    # answers while a tool was refused
        f"{METH}\n{BASH_OK}\n{FINAL}",  # retries with a tool that works, then closes
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock)

    notices = _refusal_notices(result)
    assert len(notices) == 1, "the close must be refused exactly once"
    assert "NoSuchTool" in notices[0], "the message must name the failing tool"
    assert "Error" in notices[0], "the message must carry the tool's error"
    # The retry, whose tools all worked, closes normally.
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == ANSWER


def test_final_answer_beside_a_successful_tool_closes_immediately():
    """A tool that did its job never blocks the close."""
    mock = MockLLM([
        f"{METH}\n{BASH_OK}\n{FINAL}",
        "JAMAIS CONSOMMÉ",
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock)

    assert not _refusal_notices(result)
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == ANSWER
    assert mock.call_count == 1


def test_failing_tests_reported_by_a_tool_that_ran_still_close():
    """A test run reporting failures is a SUCCESSFUL call: the agent must be able to
    deliver 'the tests fail for reason X' without the loop second-guessing it."""
    verdict = "2 failed, 1 passed"
    run = ('<tool_use name="Bash" id="b1">'
           f'<param name="command">echo "{verdict}"</param></tool_use>')
    answer = "2 tests échouent : expected 4, got 5."
    final = ('<tool_use name="FinalAnswer" id="f1">'
             f'<param name="answer">{answer}</param></tool_use>')
    mock = MockLLM([
        f"{METH}\n{run}\n{final}",
        "JAMAIS CONSOMMÉ",
    ])
    result = bouzecode(["lance les tests"], mock_llm=mock)

    bash_out = [m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert bash_out and verdict in bash_out[0], "precondition: the run reported failures"
    assert not _refusal_notices(result), "a real test failure is not a tool failure"
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == answer


def test_repeated_tool_failure_still_terminates_with_an_explicit_close_reason():
    """An agent whose tool keeps failing must still be able to end — but the close
    records WHY, so the situation is visible instead of looking like a clean finish."""
    batch = f"{METH}\n{GHOST}\n{FINAL}"
    mock = MockLLM([batch, batch, batch, batch, "JAMAIS CONSOMMÉ"])
    result = bouzecode(["fais le travail"], mock_llm=mock)

    assert len(_refusal_notices(result)) == 3, "budget is 3 refusals, then it closes"
    assert result.state.close_reason == "final_answer_over_failed_tool"
