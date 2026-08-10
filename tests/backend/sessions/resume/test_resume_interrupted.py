# [desc] Tests that interrupted agents are correctly detected and resumed when the web server restarts [/desc]
"""Crash recovery of web agents — unit level on purpose.

The behaviour under test happens between two *processes*: an agent subprocess
dies (Ctrl+C on the server) and the server, on restart, decides from the
leftover files on disk whether to respawn it. No bouzecode() conversation can
produce a half-dead subprocess plus its IPC state, so this stays a unit test
over the on-disk contract (agent JSON + IPC state.json + session JSON).

Regression pinned here: on Ctrl+C the agent used to write STATUS_FINISHED
before dying, so the restart saw "finished" and never resumed it. The IPC loop
now returns immediately on KeyboardInterrupt, leaving "running" — the marker the
restart logic reads as a crash.
"""
import json
from unittest.mock import MagicMock

import pytest

from bouzecode.web_v2.runtime.ipc import (
    run_agent_event_loop, write_state, STATUS_RUNNING, STATUS_FINISHED, from_dir,
)
from bouzecode.web_v2.runtime.runner import (
    resume_interrupted_agents, _session_has_pending_tool_calls,
)


@pytest.fixture
def tmp_agents_dir(tmp_path, monkeypatch):
    """Redirect AGENTS_DIR to a tmp directory."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    monkeypatch.setattr("bouzecode.web_v2.runtime.runner.AGENTS_DIR", agents_dir)
    return agents_dir


@pytest.fixture
def make_agent_json(tmp_agents_dir, tmp_path):
    """Helper to create an agent JSON file + optional IPC dir + session."""

    def _make(agent_id="test-agent", pid=99999, ipc_status=None,
              session_messages=None, returncode=None, auto_retry_count=0):
        ipc_dir = tmp_path / "ipc" / agent_id
        ipc_dir.mkdir(parents=True, exist_ok=True)

        session_path = tmp_path / "sessions" / f"{agent_id}.session.json"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        if session_messages is not None:
            session_path.write_text(
                json.dumps({"messages": session_messages}), encoding="utf-8"
            )

        if ipc_status is not None:
            ipc_paths = from_dir(str(ipc_dir))
            write_state(ipc_paths, ipc_status)

        agent_data = {
            "agent_id": agent_id,
            "pid": pid,
            "model": "test-model",
            "prompt": "test prompt",
            "cwd": str(tmp_path),
            "ipc_dir": str(ipc_dir),
            "session_path": str(session_path),
            "stdout_path": str(tmp_path / f"{agent_id}.stdout"),
            "started_at": "2026-05-05T10:00:00Z",
            "finished_at": "",
            "returncode": returncode,
            "auto_retry_count": auto_retry_count,
        }
        agent_file = tmp_agents_dir / f"{agent_id}.json"
        agent_file.write_text(json.dumps(agent_data), encoding="utf-8")
        # Create stdout file so _respawn can open it
        (tmp_path / f"{agent_id}.stdout").write_text("", encoding="utf-8")
        return agent_data

    return _make


def _session_with_pending_tool_calls():
    """Session messages where last assistant msg has unresolved tool_calls."""
    return [
        {"role": "user", "content": "Do something"},
        {
            "role": "assistant",
            "content": "I'll help.",
            "tool_calls": [
                {"id": "tc_1", "name": "Bash", "input": {"command": "echo hi"}},
                {"id": "tc_2", "name": "Read", "input": {"file_path": "/tmp/x"}},
            ],
        },
        # Only tc_1 resolved — tc_2 is pending
        {"role": "tool", "tool_call_id": "tc_1", "name": "Bash", "content": "hi"},
    ]


def _session_fully_resolved():
    """Session where all tool_calls are resolved."""
    return [
        {"role": "user", "content": "Do something"},
        {
            "role": "assistant",
            "content": "I'll help.",
            "tool_calls": [
                {"id": "tc_1", "name": "Bash", "input": {"command": "echo hi"}},
            ],
        },
        {"role": "tool", "tool_call_id": "tc_1", "name": "Bash", "content": "hi"},
        {"role": "assistant", "content": "Done."},
    ]


class TestSessionHasPendingToolCalls:
    def test_pending_tool_calls_detected(self, tmp_path):
        session_path = tmp_path / "s.json"
        session_path.write_text(
            json.dumps({"messages": _session_with_pending_tool_calls()}),
            encoding="utf-8",
        )
        assert _session_has_pending_tool_calls(str(session_path)) is True

    def test_fully_resolved_not_pending(self, tmp_path):
        session_path = tmp_path / "s.json"
        session_path.write_text(
            json.dumps({"messages": _session_fully_resolved()}),
            encoding="utf-8",
        )
        assert _session_has_pending_tool_calls(str(session_path)) is False

    def test_missing_file_returns_false(self, tmp_path):
        assert _session_has_pending_tool_calls(str(tmp_path / "nope.json")) is False


class TestResumeInterruptedAgents:
    def test_interrupted_agent_with_pending_tool_calls_is_resumed(
        self, make_agent_json, monkeypatch
    ):
        """Agent crashed (dead pid, IPC state 'running', pending tool_calls) → resumed."""
        make_agent_json(
            agent_id="crashed-agent",
            pid=99999,
            ipc_status=STATUS_RUNNING,
            session_messages=_session_with_pending_tool_calls(),
        )
        # pid 99999 should not exist, but mock to be safe
        monkeypatch.setattr("bouzecode.web_v2.runtime.runner.psutil.pid_exists", lambda pid: False)
        # Mock subprocess.Popen to avoid spawning real process
        mock_popen = MagicMock()
        mock_popen.pid = 12345
        monkeypatch.setattr("bouzecode.web_v2.runtime.runner.subprocess.Popen", lambda *a, **kw: mock_popen)

        resumed = resume_interrupted_agents()
        assert len(resumed) == 1
        assert resumed[0].agent_id == "crashed-agent"

    def test_finished_agent_not_resumed(self, make_agent_json, monkeypatch):
        """Agent with IPC 'finished' state → returncode=0 → NOT resumed."""
        make_agent_json(
            agent_id="done-agent",
            pid=99999,
            ipc_status=STATUS_FINISHED,
            session_messages=_session_with_pending_tool_calls(),
        )
        monkeypatch.setattr("bouzecode.web_v2.runtime.runner.psutil.pid_exists", lambda pid: False)

        resumed = resume_interrupted_agents()
        assert len(resumed) == 0

    def test_interrupted_without_pending_tool_calls_not_resumed(
        self, make_agent_json, monkeypatch
    ):
        """Agent crashed but session fully resolved → NOT resumed."""
        make_agent_json(
            agent_id="resolved-agent",
            pid=99999,
            ipc_status=STATUS_RUNNING,
            session_messages=_session_fully_resolved(),
        )
        monkeypatch.setattr("bouzecode.web_v2.runtime.runner.psutil.pid_exists", lambda pid: False)

        resumed = resume_interrupted_agents()
        assert len(resumed) == 0

    def test_agent_with_cancel_flag_not_resumed(self, make_agent_json, tmp_path, monkeypatch):
        """Agent interrupted by user cancel (cancel.flag present) → NOT resumed."""
        make_agent_json(
            agent_id="cancelled-agent",
            pid=99999,
            ipc_status=STATUS_RUNNING,
            session_messages=_session_with_pending_tool_calls(),
        )
        # Create cancel.flag in IPC dir
        cancel_flag = tmp_path / "ipc" / "cancelled-agent" / "cancel.flag"
        cancel_flag.write_text("", encoding="utf-8")

        monkeypatch.setattr("bouzecode.web_v2.runtime.runner.psutil.pid_exists", lambda pid: False)

        resumed = resume_interrupted_agents()
        assert len(resumed) == 0


class TestIpcEventLoopKeyboardInterrupt:
    def test_keyboard_interrupt_leaves_running_state(self, tmp_path, monkeypatch):
        """A Ctrl+C'd agent leaves its IPC state on 'running', so the next server
        start sees a crash to recover instead of a clean 'finished'."""
        # The event loop bootstraps readme_sync on the current repo before running
        # the turn — irrelevant here and very slow, so it is stubbed out.
        monkeypatch.setattr(
            "bouzecode.web_v2.runtime.ipc._maybe_bootstrap_readme", lambda root: None
        )
        ipc_dir = tmp_path / "ipc"
        ipc_dir.mkdir()
        paths = from_dir(str(ipc_dir))

        def raise_interrupt(prompt):
            raise KeyboardInterrupt()

        run_agent_event_loop("test", raise_interrupt, paths)

        from bouzecode.web_v2.runtime.ipc import read_state
        assert read_state(paths).get("status") == "running"
