"""Forced-close IPC stamping + reconcile behaviour.

Prod bug (agent 8469516f628c, manager profile, web-dispatched): a forced close
(BREAK with close_reason=final_answer_nudge_exhausted/never_called/meta_only_cap)
left the IPC state.json stuck on {"status":"running","turn":1}. The manager
on_completion hook does a BLOCKING http_post (server test-gate, up to ~1900s) that
can reap/kill the agent process BEFORE run_agent_event_loop writes FINISHED — so the
IPC never leaves "running", and reconcile_dead_agents sees a dead pid + running IPC
=> returncode -1 (fake crash) => ticket marked "planté".

Fix under test:
 1. _fire_completion invokes config["_ipc_finish_cb"](close_reason) BEFORE firing the
    (potentially process-killing) on_completion hook, stamping FINISHED+close_reason.
 2. run_agent_event_loop no longer clobbers an already-written FINISHED (turn reset
    to 1 / close_reason erased) when it later returns normally.

These are real behaviours exercised at the closest public entry points (no mock):
_fire_completion, run_agent_event_loop, reconcile_dead_agents — with pure in-memory
recorders and real on-disk IPC dirs.

NB web_v2 : seuls `final_answer` et `final_answer_deferred` comptent comme clôture
GRACIEUSE (`runner._GRACEFUL_CLOSE_REASONS`). Une clôture forcée
(nudge_exhausted/never_called/meta_only_cap) est délibérément classée crash — les tests
de réconciliation ci-dessous suivent ce contrat, pas l'ancien.
"""
import json
import subprocess
import sys

from bouzecode.backend.agent import loop as agent_loop
from bouzecode.backend.agent.hooks import pipeline
from bouzecode.web_v2.runtime import ipc
from bouzecode.web_v2.runtime.runner.agent_fiche import Agent, _agent_from_dict
from bouzecode.web_v2.runtime.runner.agent_registre import reconcile_dead_agents


class _State:
    """Minimal agent state stub: only turn_count/messages/close_reason are read by
    _fire_completion -> completion_context (_extract_final_text reads messages)."""
    def __init__(self, turn_count=1):
        self.turn_count = turn_count
        self.close_reason = ""
        self.messages = []
        self.thinking_log = []


def test_fire_completion_stamps_close_reason_before_hook(monkeypatch):
    """On a forced close, _fire_completion must call the IPC finish callback with the
    close_reason BEFORE the (blocking, possibly process-killing) on_completion hook."""
    # Guarantee an empty hook registry: fire() becomes a no-op, so the callback is the
    # only observable effect.
    monkeypatch.setattr(pipeline, "_HOOKS", {})
    recorded = []
    config = {"_ipc_finish_cb": lambda cr: recorded.append(cr)}
    state = _State(turn_count=29)

    agent_loop._fire_completion(state, config, "final_answer_nudge_exhausted")

    assert recorded == ["final_answer_nudge_exhausted"]


def test_run_agent_event_loop_keeps_existing_finished(tmp_path):
    """If the finish callback already stamped FINISHED+close_reason+turn, the normal
    end-of-loop write must NOT overwrite it back to turn=1 / drop the close_reason."""
    paths = ipc.from_dir(tmp_path / "agent01.ipc")

    # The finish callback (fired by _fire_completion INSIDE run_query) stamps
    # FINISHED+close_reason+turn while the agent is still running its turns.
    def _run_query(_prompt):
        ipc.write_state(paths, ipc.STATUS_FINISHED, turn=29,
                        close_reason="final_answer_nudge_exhausted")

    # keep_warm=False : le tour unique historique. Avec le défaut (warm), le process reste
    # résident 900 s à guetter un follow-up — ce n'est pas la fin de boucle qu'on teste ici.
    ipc.run_agent_event_loop("prompt", _run_query, paths, keep_warm=False)

    state = ipc.read_state(paths)
    assert state["status"] == ipc.STATUS_FINISHED
    assert state["turn"] == 29
    assert state["close_reason"] == "final_answer_nudge_exhausted"


def test_run_agent_event_loop_finishes_and_keeps_turn(tmp_path):
    """Normal finish with a running IPC at turn N: the tail write must land FINISHED
    while preserving the current turn (not resetting it to 1)."""
    paths = ipc.from_dir(tmp_path / "agent02.ipc")
    ipc.write_state(paths, ipc.STATUS_RUNNING, turn=7)

    ipc.run_agent_event_loop("prompt", lambda _p: None, paths, keep_warm=False)

    state = ipc.read_state(paths)
    assert state["status"] == ipc.STATUS_FINISHED
    assert state["turn"] == 7


def _write_dead_agent(tmp_path, agent_id, ipc_status, **ipc_extra):
    """Spawn a real subprocess, kill it (dead pid), and persist an Agent + IPC state.
    Returns the terminated Popen so the caller can assert it is dead."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    proc.terminate()
    proc.wait(timeout=5)

    ipc_dir = tmp_path / f"{agent_id}.ipc"
    ipc_dir.mkdir()
    (ipc_dir / "state.json").write_text(
        json.dumps({"status": ipc_status, "updated_at": 0, **ipc_extra}),
        encoding="utf-8",
    )
    (tmp_path / f"{agent_id}.json").write_text(
        json.dumps({"agent_id": agent_id, "prompt": "p", "model": "m",
                    "cwd": str(tmp_path), "pid": proc.pid,
                    "started_at": "2026-01-01T00:00:00Z",
                    "ipc_dir": str(ipc_dir)}),
        encoding="utf-8",
    )
    return proc


def test_reconcile_dead_agent_finished_is_graceful(tmp_path, monkeypatch):
    """Un agent au pid mort dont l'IPC porte une clôture gracieuse n'est PAS signalé crashé."""
    monkeypatch.setattr("bouzecode.web_v2.runtime.runner.agent_fiche.AGENTS_DIR", tmp_path)
    proc = _write_dead_agent(tmp_path, "gracefulcls", ipc.STATUS_FINISHED,
                             close_reason="final_answer")

    crashed = reconcile_dead_agents()

    assert crashed == []
    data = json.loads((tmp_path / "gracefulcls.json").read_text(encoding="utf-8"))
    agent = _agent_from_dict(data)
    assert agent.returncode == 0
    assert agent.finished_at
    assert proc.poll() is not None


def test_reconcile_dead_agent_running_is_crash(tmp_path, monkeypatch):
    """À l'inverse, un agent au pid mort dont l'IPC est resté « running » est signalé crashé."""
    monkeypatch.setattr("bouzecode.web_v2.runtime.runner.agent_fiche.AGENTS_DIR", tmp_path)
    _write_dead_agent(tmp_path, "stuckrunning", ipc.STATUS_RUNNING)

    crashed = reconcile_dead_agents()

    assert crashed == ["stuckrunning"]
    data = json.loads((tmp_path / "stuckrunning.json").read_text(encoding="utf-8"))
    agent = _agent_from_dict(data)
    assert agent.returncode == -1
