# [desc] E2E test verifying interrupted agents without pending tool_calls are resumed on recovery [/desc]
"""Test that resume_interrupted_agents relances agents that were interrupted
even when they have NO pending tool_calls (i.e. they were mid-thinking).

This test should FAIL before the fix (currently, such agents are skipped).
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_agents_dir(tmp_path, monkeypatch):
    """Set up a fake AGENTS_DIR with one interrupted agent (no pending tool_calls)."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    # Create a fake session file with NO pending tool_calls
    session_path = agents_dir / "abc123dead00.session.json"
    session_data = {
        "messages": [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "I'm thinking about this..."},
        ]
    }
    session_path.write_text(json.dumps(session_data), encoding="utf-8")

    # Create the agent JSON (PID that doesn't exist)
    agent_data = {
        "agent_id": "abc123dead00",
        "prompt": "do something",
        "model": "test-model",
        "cwd": str(tmp_path),
        "pid": 99999999,  # Non-existent PID
        "started_at": "2026-05-11T10:00:00Z",
        "stdout_path": str(agents_dir / "abc123dead00.out.log"),
        "session_path": str(session_path),
        "ipc_dir": str(agents_dir / "abc123dead00.ipc"),
        "auto_retry_count": 0,
    }
    (agents_dir / "abc123dead00.json").write_text(
        json.dumps(agent_data), encoding="utf-8"
    )

    # Create the IPC dir with a non-done state
    ipc_dir = agents_dir / "abc123dead00.ipc"
    ipc_dir.mkdir()
    # Write state as "running" (not finished/awaiting)
    (ipc_dir / "state.json").write_text(
        json.dumps({"status": "running"}), encoding="utf-8"
    )

    # Monkeypatch AGENTS_DIR
    monkeypatch.setattr("bouzecode.web_v2.runtime.runner.AGENTS_DIR", agents_dir)

    # Monkeypatch psutil.pid_exists to return False for our fake PID
    original_pid_exists = __import__("psutil").pid_exists
    monkeypatch.setattr(
        "psutil.pid_exists", lambda pid: False if pid == 99999999 else original_pid_exists(pid)
    )

    # Monkeypatch _respawn to avoid actually spawning a process
    mock_respawn = MagicMock(side_effect=lambda agent, **kwargs: agent)
    monkeypatch.setattr("bouzecode.web_v2.runtime.runner._respawn", mock_respawn)

    return agents_dir, mock_respawn


def test_resume_interrupted_agent_without_pending_tool_calls(fake_agents_dir):
    """An interrupted agent with NO pending tool_calls SHOULD be resumed.

    Currently this test FAILS because the code skips such agents at line 362.
    """
    from bouzecode.web_v2.runtime.runner import resume_interrupted_agents

    agents_dir, mock_respawn = fake_agents_dir
    resumed = resume_interrupted_agents()

    # The agent should have been resumed (currently it's NOT → test fails)
    assert len(resumed) == 1, (
        f"Expected 1 resumed agent, got {len(resumed)}. "
        "Agent without pending tool_calls was not auto-resumed."
    )
    assert resumed[0].agent_id == "abc123dead00"
    # _respawn should have been called
    assert mock_respawn.called
