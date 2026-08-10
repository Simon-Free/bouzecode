# [desc] Tests wake.py : le reconciler gracieux replie sur l'IPC quand le session JSON a un close_reason vide. [/desc]
"""Filet de defense cote wake.py : le reconciler gracieux doit reconnaitre un run
gracieux meme si le session JSON a un close_reason vide, en repliant sur l'IPC de l'agent.

SANS unittest.mock : vrai Agent (dataclass) + vrai ipc.write_state pour poser state.json."""
from bouzecode.web_v2.runtime import ipc
from bouzecode.web_v2.runtime.runner import Agent
from bouzecode.web_v2.services.work.wake import _close_reason_with_ipc_fallback


def _agent(tmp_path, ipc_status=None, ipc_close_reason=None):
    ipc_dir = tmp_path / "a.ipc"
    if ipc_status is not None:
        extra = {} if ipc_close_reason is None else {"close_reason": ipc_close_reason}
        ipc.write_state(ipc.from_dir(str(ipc_dir)), ipc_status, turn=1, **extra)
    return Agent(agent_id="a", prompt="p", model="m", cwd=".", pid=1, started_at="",
                 ipc_dir=str(ipc_dir))


def test_empty_session_falls_back_to_ipc_final_answer(tmp_path):
    agent = _agent(tmp_path, ipc_status="finished", ipc_close_reason="final_answer")
    assert _close_reason_with_ipc_fallback(agent, "") == "final_answer"


def test_session_close_reason_wins_over_ipc(tmp_path):
    agent = _agent(tmp_path, ipc_status="finished", ipc_close_reason="final_answer")
    # Session non vide -> on la renvoie telle quelle, sans consulter l'IPC.
    assert _close_reason_with_ipc_fallback(agent, "text_no_tools") == "text_no_tools"


def test_agent_none_returns_empty(tmp_path):
    # Agent decharge (nettoye apres mort) : pas d'IPC lisible -> reste vide (comportement session).
    assert _close_reason_with_ipc_fallback(None, "") == ""


def test_empty_session_ipc_running_returns_empty(tmp_path):
    agent = _agent(tmp_path, ipc_status="running")
    assert _close_reason_with_ipc_fallback(agent, "") == ""
