# [desc] Le constat de fin de run replie sur l'IPC quand la session a un close_reason vide (`constats.cloture_lue`). [/desc]
"""Filet de défense du watchdog : une fin de run gracieuse doit être reconnue même si la
session JSON a un close_reason vide, en repliant sur l'IPC de l'agent.

SANS unittest.mock : vrai Agent (dataclass) + vrai ipc.write_state pour poser state.json."""
import json

from bouzecode.web_v2.runtime import ipc
from bouzecode.web_v2.runtime.runner.agent_fiche import Agent
from bouzecode.web_v2.services.work.constats import cloture_lue


def _agent(tmp_path, ipc_status=None, ipc_close_reason=None, session_close_reason=None):
    ipc_dir = tmp_path / "a.ipc"
    if ipc_status is not None:
        extra = {} if ipc_close_reason is None else {"close_reason": ipc_close_reason}
        ipc.write_state(ipc.from_dir(str(ipc_dir)), ipc_status, turn=1, **extra)
    session = tmp_path / "a.session.json"
    if session_close_reason is not None:
        session.write_text(json.dumps({"messages": [], "close_reason": session_close_reason}),
                           encoding="utf-8")
    return Agent(agent_id="a", prompt="p", model="m", cwd=".", pid=1, started_at="",
                 ipc_dir=str(ipc_dir), session_path=str(session))


def test_empty_session_falls_back_to_ipc_final_answer(tmp_path):
    agent = _agent(tmp_path, ipc_status="finished", ipc_close_reason="final_answer")
    assert cloture_lue(agent)[0] == "final_answer"


def test_session_close_reason_wins_over_ipc(tmp_path):
    agent = _agent(tmp_path, ipc_status="finished", ipc_close_reason="final_answer",
                   session_close_reason="text_no_tools")
    assert cloture_lue(agent)[0] == "text_no_tools"


def test_empty_session_ipc_running_returns_empty(tmp_path):
    agent = _agent(tmp_path, ipc_status="running")
    assert cloture_lue(agent)[0] == ""
