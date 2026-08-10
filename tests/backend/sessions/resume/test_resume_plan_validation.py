# [desc] Tests that an agent parked on plan validation survives a web-server restart instead of being marked crashed [/desc]
"""An agent waiting for the user to approve a plan must survive a server restart.

Unit level on purpose: the situation is a *dead process* whose leftover IPC
state still says "awaiting_plan_validation". A bouzecode() conversation cannot
produce a dead subprocess, so we build the on-disk state (agent JSON + IPC
state.json) the restart logic reads.
"""
import json
from datetime import datetime

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.runtime.state_streams import _agent_category


@pytest.fixture
def fake_agents_dir(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    return agents_dir


def _create_agent_json(agents_dir, ipc_dir, *, agent_id="048b76cf1469", pid=99999):
    """Create a minimal agent JSON file + IPC state."""
    agent_data = {
        "agent_id": agent_id,
        "pid": pid,
        "returncode": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": "",
        "prompt": "test prompt",
        "model": "test-model",
        "cwd": "C:/fake",
        "ipc_dir": str(ipc_dir),
        "session_path": "",
        "auto_retry_count": 0,
    }
    agent_file = agents_dir / f"{agent_id}.json"
    agent_file.write_text(json.dumps(agent_data), encoding="utf-8")
    return agent_file


def _write_ipc_state(ipc_dir, status):
    """Write IPC state.json mimicking ipc.write_state."""
    ipc_dir.mkdir(parents=True, exist_ok=True)
    state_file = ipc_dir / "state.json"
    state_file.write_text(json.dumps({"status": status}), encoding="utf-8")
    return state_file


class TestResumePlanValidation:
    def test_resume_preserves_awaiting_plan_validation(
        self, fake_agents_dir, tmp_path, monkeypatch
    ):
        """Agent awaiting plan validation should NOT be overwritten to finished."""
        ipc_dir = tmp_path / "ipc_test"
        _write_ipc_state(ipc_dir, "awaiting_plan_validation")
        _create_agent_json(fake_agents_dir, ipc_dir)

        monkeypatch.setattr("psutil.pid_exists", lambda pid: False)

        runner.resume_interrupted_agents()

        # IPC state must be preserved
        state = json.loads((ipc_dir / "state.json").read_text())
        assert state["status"] == "awaiting_plan_validation"

        # Agent returncode must be 0 (not -1 crash)
        agent_data = json.loads(
            (fake_agents_dir / "048b76cf1469.json").read_text(encoding="utf-8")
        )
        assert agent_data["returncode"] == 0

    def test_agent_category_awaiting_plan_validation(
        self, fake_agents_dir, tmp_path, monkeypatch
    ):
        """Agent with awaiting_plan_validation must show in 'awaiting' column."""
        ipc_dir = tmp_path / "ipc_test2"
        _write_ipc_state(ipc_dir, "awaiting_plan_validation")
        _create_agent_json(fake_agents_dir, ipc_dir, agent_id="abc123")

        monkeypatch.setattr("psutil.pid_exists", lambda pid: False)

        runner.resume_interrupted_agents()

        agent_file = fake_agents_dir / "abc123.json"
        data = json.loads(agent_file.read_text(encoding="utf-8"))
        agent = runner._agent_from_dict(data)
        # A paused plan-validation agent stays in the "awaiting" column even
        # though its process is gone — the user still owes it an answer.
        agent.session_path = str(tmp_path / "session.json")
        assert _agent_category(agent) == "awaiting"

    def test_resume_still_marks_crashed_agents(
        self, fake_agents_dir, tmp_path, monkeypatch
    ):
        """Agent with IPC 'running' (actual crash) still gets returncode=-1."""
        ipc_dir = tmp_path / "ipc_crash"
        _write_ipc_state(ipc_dir, "running")
        _create_agent_json(fake_agents_dir, ipc_dir, agent_id="crashed01")

        monkeypatch.setattr("psutil.pid_exists", lambda pid: False)

        runner.resume_interrupted_agents()

        state = json.loads((ipc_dir / "state.json").read_text())
        assert state["status"] == "finished"

        agent_data = json.loads(
            (fake_agents_dir / "crashed01.json").read_text(encoding="utf-8")
        )
        assert agent_data["returncode"] == -1
