# [desc] Tests for agent JSON parsing, dataclass round-trip, and ANSI/spinner line filtering utilities. [/desc]
"""Tests for web.runner — agent JSON parsing, listing, stream filtering."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from dataclasses import asdict

import pytest

from web.runner import Agent, _agent_from_dict, _REQUIRED_KEYS, refresh_agent_status, get_ipc_state, _save


# ── _agent_from_dict ──────────────────────────────────────────────────

VALID_AGENT_DATA = {
    "agent_id": "abc123",
    "prompt": "do stuff",
    "model": "claude-opus-4-6",
    "cwd": "/tmp",
    "pid": 1234,
    "started_at": "2026-04-14T10:00:00Z",
}


def test_agent_from_dict_valid():
    agent = _agent_from_dict(VALID_AGENT_DATA)
    assert agent is not None
    assert agent.agent_id == "abc123"
    assert agent.model == "claude-opus-4-6"
    assert agent.pid == 1234


def test_agent_from_dict_with_extra_keys():
    data = {**VALID_AGENT_DATA, "session_id": "xyz", "unknown_field": 42}
    agent = _agent_from_dict(data)
    assert agent is not None
    assert agent.agent_id == "abc123"
    assert not hasattr(agent, "session_id")


def test_agent_from_dict_with_optional_fields():
    data = {**VALID_AGENT_DATA, "finished_at": "2026-04-14T11:00:00Z", "returncode": 0}
    agent = _agent_from_dict(data)
    assert agent is not None
    assert agent.finished_at == "2026-04-14T11:00:00Z"
    assert agent.returncode == 0


def test_agent_from_dict_missing_required_returns_none():
    for key in _REQUIRED_KEYS:
        incomplete = {k: v for k, v in VALID_AGENT_DATA.items() if k != key}
        assert _agent_from_dict(incomplete) is None, f"Should be None when missing {key}"


def test_agent_from_dict_session_json_returns_none():
    session_data = {
        "session_id": "477b981b",
        "saved_at": "2026-04-14 13:01:35",
        "messages": [],
    }
    assert _agent_from_dict(session_data) is None


def test_agent_from_dict_empty_dict_returns_none():
    assert _agent_from_dict({}) is None


# ── Agent dataclass round-trip ────────────────────────────────────────

def test_agent_roundtrip():
    agent = Agent(**VALID_AGENT_DATA)
    data = asdict(agent)
    restored = _agent_from_dict(data)
    assert restored is not None
    assert restored.agent_id == agent.agent_id
    assert restored.prompt == agent.prompt


# ── ANSI / spinner filtering (app.py logic) ──────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07")
_SPINNER_RE = re.compile(r"^\s*[\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f\u2818\u2819\u2839\u2838]")


def _clean_line(raw: str) -> str | None:
    clean = _ANSI_RE.sub("", raw).rstrip()
    if not clean or _SPINNER_RE.match(clean):
        return None
    return clean


def test_ansi_stripping():
    assert _clean_line("\x1b[32mHello\x1b[0m") == "Hello"


def test_empty_line_filtered():
    assert _clean_line("") is None
    assert _clean_line("   ") is None


def test_normal_line_preserved():
    assert _clean_line("Writing file main.py") == "Writing file main.py"


# ── _clean_stdout (web.app) ──────────────────────────────────────────

from web.stdout_filter import clean_stdout as _clean_stdout


def test_clean_stdout_filters_spinner_lines():
    raw = "Hello\n\r  \u280b \x1b[2mspinner\x1b[0m   \r  \u2819 \x1b[2mspinner\x1b[0m   \nWorld"
    assert _clean_stdout(raw) == "Hello\nWorld"


def test_clean_stdout_simulates_cr_overwrite():
    raw = "first\rsecond\rthird"
    assert _clean_stdout(raw) == "third"


def test_clean_stdout_strips_ansi():
    raw = "\x1b[32mGreen\x1b[0m text"
    assert _clean_stdout(raw) == "Green text"


def test_clean_stdout_empty():
    assert _clean_stdout("") == ""


def test_clean_stdout_preserves_normal_multiline():
    raw = "line one\nline two\nline three"
    assert _clean_stdout(raw) == "line one\nline two\nline three"


def test_clean_stdout_cr_only_spinner_gone():
    """A line with only \\r-separated spinner frames should vanish entirely."""
    raw = "\r  \u280b \x1b[2mtext\x1b[0m   \r  \u2819 \x1b[2mtext\x1b[0m   \r" + " " * 50 + "\r"
    assert _clean_stdout(raw) == ""


# ── refresh_agent_status: IPC "finished" terminates stuck process ─────

def test_refresh_marks_finished_when_ipc_finished(tmp_path, monkeypatch):
    """A live process with IPC status=finished gets terminated and marked done."""
    import subprocess, sys, os

    monkeypatch.setattr("web.runner.AGENTS_DIR", tmp_path)

    # Spawn a real subprocess that sleeps forever
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    ipc_dir = tmp_path / "stuck01.ipc"
    ipc_dir.mkdir()
    # Write IPC state = finished (simulates agent event loop done but process hung)
    (ipc_dir / "state.json").write_text(
        json.dumps({"status": "finished", "updated_at": 0}), encoding="utf-8",
    )

    agent = Agent(
        agent_id="stuck01", prompt="test", model="m", cwd=str(tmp_path),
        pid=proc.pid, started_at="2026-01-01T00:00:00Z",
        stdout_path=str(tmp_path / "stuck01.out.log"),
        session_path=str(tmp_path / "stuck01.session.json"),
        ipc_dir=str(ipc_dir),
    )
    (tmp_path / "stuck01.json").write_text(
        json.dumps({"agent_id": "stuck01", "prompt": "test", "model": "m",
                     "cwd": str(tmp_path), "pid": proc.pid,
                     "started_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    result = refresh_agent_status(agent)
    assert result.returncode == 0
    assert result.finished_at != ""

    # Process should be terminated
    proc.wait(timeout=5)
    assert proc.poll() is not None


def test_refresh_keeps_running_when_ipc_idle(tmp_path, monkeypatch):
    """A live process with IPC status=idle should NOT be terminated."""
    import subprocess, sys

    monkeypatch.setattr("web.runner.AGENTS_DIR", tmp_path)

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    ipc_dir = tmp_path / "alive01.ipc"
    ipc_dir.mkdir()
    (ipc_dir / "state.json").write_text(
        json.dumps({"status": "idle", "updated_at": 0}), encoding="utf-8",
    )

    agent = Agent(
        agent_id="alive01", prompt="test", model="m", cwd=str(tmp_path),
        pid=proc.pid, started_at="2026-01-01T00:00:00Z",
        stdout_path=str(tmp_path / "alive01.out.log"),
        session_path=str(tmp_path / "alive01.session.json"),
        ipc_dir=str(ipc_dir),
    )

    result = refresh_agent_status(agent)
    assert result.returncode is None  # still running

    # Cleanup
    proc.terminate()
    proc.wait(timeout=5)
