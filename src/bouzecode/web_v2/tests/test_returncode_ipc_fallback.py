# [desc] Tests: session close_reason vide + IPC finished/final_answer → rc gracieux (0), jamais crash. [/desc]
"""Filet de defense cote web/runner.py : un run gracieux dont le session JSON porte
close_reason='' MAIS dont l'IPC state.json dit {status:finished, close_reason:final_answer}
doit etre classe GRACIEUX (rc=0), JAMAIS crash (rc=-1).

SANS unittest.mock : on construit un vrai Agent (dataclass) pointant sur un fichier
session tmp et un ipc_dir tmp dont le state.json est ecrit par le VRAI ipc.write_state."""
import json

from bouzecode.web_v2.runtime import ipc
from bouzecode.web_v2.runtime.runner import Agent, _returncode_from_session


def _agent(tmp_path, session_close_reason, ipc_status=None, ipc_close_reason=None):
    session_file = tmp_path / "a.session.json"
    session_file.write_text(json.dumps({"close_reason": session_close_reason}), encoding="utf-8")
    ipc_dir = tmp_path / "a.ipc"
    if ipc_status is not None:
        extra = {} if ipc_close_reason is None else {"close_reason": ipc_close_reason}
        ipc.write_state(ipc.from_dir(str(ipc_dir)), ipc_status, turn=1, **extra)
    return Agent(
        agent_id="a", prompt="p", model="m", cwd=".", pid=1, started_at="",
        session_path=str(session_file), ipc_dir=str(ipc_dir),
    )


def test_empty_session_but_ipc_final_answer_is_graceful(tmp_path):
    agent = _agent(tmp_path, "", ipc_status="finished", ipc_close_reason="final_answer")
    assert _returncode_from_session(agent) == 0


def test_empty_session_ipc_finished_deferred_is_graceful(tmp_path):
    agent = _agent(tmp_path, "", ipc_status="finished", ipc_close_reason="final_answer_deferred")
    assert _returncode_from_session(agent) == 0


def test_session_close_reason_wins_when_present(tmp_path):
    agent = _agent(tmp_path, "final_answer", ipc_status="running")
    assert _returncode_from_session(agent) == 0


def test_empty_session_ipc_running_is_crash(tmp_path):
    agent = _agent(tmp_path, "", ipc_status="running")
    assert _returncode_from_session(agent) == -1


def test_empty_session_no_ipc_is_crash(tmp_path):
    agent = _agent(tmp_path, "")  # aucun state.json ecrit
    assert _returncode_from_session(agent) == -1


def test_empty_session_ipc_finished_without_close_reason_is_crash(tmp_path):
    # IPC finished mais close_reason absent (pas gracieux prouve) -> reste crash.
    agent = _agent(tmp_path, "", ipc_status="finished")
    assert _returncode_from_session(agent) == -1
