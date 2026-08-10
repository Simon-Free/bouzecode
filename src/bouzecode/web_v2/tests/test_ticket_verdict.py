# [desc] _find_verdict: VERDICT parsé depuis texte assistant, tool_call FinalAnswer ou tool_result. [/desc]
"""Reproduit le bug du 2026-06-10 : un validateur CI livrant son verdict via le
tool FinalAnswer (et non en texte assistant) laissait run["verdict"] vide."""
import json

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import tickets


def _agent_with_session(tmp_path, messages):
    session = tmp_path / "agent.session.json"
    session.write_text(json.dumps({"messages": messages}), encoding="utf-8")
    return runner.Agent(
        agent_id="a1", prompt="p", model="m", cwd=str(tmp_path),
        pid=0, started_at="now", session_path=str(session),
    )


def test_verdict_in_assistant_text_with_enforcement_tail(tmp_path):
    agent = _agent_with_session(tmp_path, [
        {"role": "assistant", "content": "Tests verts.\nVERDICT: OK"},
        {"role": "assistant", "content": "."},
    ])
    assert tickets._find_verdict(agent) == "OK"


def test_verdict_in_final_answer_tool_result(tmp_path):
    agent = _agent_with_session(tmp_path, [
        {"role": "assistant", "content": "Le test échoue à l'import."},
        {"role": "tool", "name": "FinalAnswer",
         "content": "Session closing — final answer delivered:\n## CI\n\nVERDICT: KO\n- import error"},
    ])
    assert tickets._find_verdict(agent) == "KO"


def test_verdict_in_final_answer_tool_call_input(tmp_path):
    agent = _agent_with_session(tmp_path, [
        {"role": "assistant", "content": "",
         "tool_calls": [{"name": "FinalAnswer", "id": "f1",
                         "input": {"answer": "Bilan.\nVERDICT: KO"}}]},
    ])
    assert tickets._find_verdict(agent) == "KO"


def test_no_verdict_returns_none(tmp_path):
    agent = _agent_with_session(tmp_path, [
        {"role": "assistant", "content": "rien à signaler"},
    ])
    assert tickets._find_verdict(agent) is None
