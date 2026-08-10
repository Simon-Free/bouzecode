# [desc] E2E and unit tests for terminal sub-agent spawning, --result-file CLI flag, and command building. [/desc]
"""E2E tests for terminal sub-agent spawning.

Tests:
1. --result-file CLI flag writes last assistant message to file
2. build_terminal_command() returns correct command for wt
3. build_terminal_command() returns correct command for cmd fallback
4. spawn_in_terminal() creates a real process (integration)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from bouzecode.backend.multi_agent.terminal import build_terminal_command


class TestBuildTerminalCommand:
    """Test the pure build_terminal_command function."""

    def test_wt_command_structure(self):
        cmd = build_terminal_command(
            prompt="do stuff",
            result_file="/tmp/r.txt",
            config={},
            terminal_app="wt",
        )
        assert isinstance(cmd, list)
        assert cmd[0] == "wt.exe"
        # Must open a NEW WINDOW (`-w -1`), not just a tab in an existing one.
        assert "-w" in cmd
        w_idx = cmd.index("-w")
        assert cmd[w_idx + 1] == "-1"
        assert "new-tab" in cmd
        assert "--title" in cmd
        assert "--result-file" in cmd
        rf_idx = cmd.index("--result-file")
        assert cmd[rf_idx + 1] == "/tmp/r.txt"
        assert "-p" in cmd
        p_idx = cmd.index("-p")
        assert cmd[p_idx + 1] == "do stuff"
        assert "--accept-all" in cmd

    def test_wt_command_with_model(self):
        cmd = build_terminal_command(
            prompt="test",
            result_file="/tmp/r.txt",
            config={"model": "claude-sonnet-4-20250514"},
            terminal_app="wt",
        )
        assert "--model" in cmd
        m_idx = cmd.index("--model")
        assert cmd[m_idx + 1] == "claude-sonnet-4-20250514"

    def test_cmd_fallback_structure(self):
        cmd = build_terminal_command(
            prompt="do stuff",
            result_file="/tmp/r.txt",
            config={},
            terminal_app="cmd",
        )
        assert isinstance(cmd, list)
        assert cmd[0] == "cmd"
        assert "/c" in cmd
        assert "start" in cmd

    def test_cmd_contains_result_file(self):
        cmd = build_terminal_command(
            prompt="hello",
            result_file="C:\\tmp\\result.txt",
            config={},
            terminal_app="cmd",
        )
        # The inner command string should contain --result-file
        full = " ".join(cmd)
        assert "--result-file" in full
        assert "C:\\tmp\\result.txt" in full

    def test_uses_current_python_executable(self):
        cmd = build_terminal_command(
            prompt="x",
            result_file="/tmp/r.txt",
            config={},
            terminal_app="wt",
        )
        assert sys.executable in cmd


class TestResultFileCLI:
    """E2E test: --result-file writes output on exit."""

    @pytest.mark.timeout(90)
    def test_result_file_written_on_exit(self, tmp_path):
        """Run bouzecode -p with --result-file and verify output is written."""
        from tests.cache_conversation_helpers import require_api_key
        require_api_key()  # live API test — skips when unreachable instead of hanging 90s
        result_file = tmp_path / "agent_result.txt"
        cmd = [
            sys.executable, "-m", "bouzecode",
            "-p", "Respond with exactly this text and nothing else: RESULT_FILE_TEST_OK_789",
            "--result-file", str(result_file),
            "--accept-all",
        ]
        env = {**os.environ, "BOUZECODE_NO_ENFORCE": "1"}
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            cwd=str(Path(__file__).parent.parent),
            env=env,
        )
        assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        assert result_file.exists(), f"Result file not created. stdout: {proc.stdout}"
        content = result_file.read_text(encoding="utf-8")
        assert len(content.strip()) > 0, "Result file is empty"
        # The LLM should have responded with something containing our marker
        assert "RESULT_FILE_TEST_OK_789" in content


class TestCmdInnerShellFlag:
    """The inner cmd shell must default to /c (auto-close) and only use /k opt-in."""

    def _inner_flag(self, config: dict) -> str:
        cmd = build_terminal_command(
            prompt="do stuff",
            result_file="/tmp/r.txt",
            config=config,
            terminal_app="cmd",
        )
        # Layout: ["cmd", "/c", "start", "<title>", "cmd", <inner_flag>, <inner>]
        assert cmd[4] == "cmd", f"unexpected layout: {cmd}"
        return cmd[5]

    def test_cmd_default_uses_c_for_inner_shell(self):
        # No debug flag → inner shell must auto-close with /c (no orphan windows).
        assert self._inner_flag(config={}) == "/c"

    def test_cmd_keep_open_uses_k_for_inner_shell(self):
        # Opt-in debug flag keeps the window open with /k.
        assert self._inner_flag(config={"_terminal_keep_open": True}) == "/k"


class _DummyProc:
    """Fake process whose poll() returns 0 immediately (like wt.exe / cmd start).

    This is exactly the case that used to break the wait loop: a launcher that
    returns right away must NOT cause the result file to be read prematurely.
    """

    def poll(self):
        return 0


class TestSpawnRoundTrip:
    """Round-trip spawn -> wait -> read result-file (the path the old test missed)."""

    def test_spawn_wait_reads_result_file(self, monkeypatch):
        from bouzecode.backend.multi_agent import terminal as terminal_mod
        from bouzecode.backend.multi_agent.tools import _spawn_terminal_agent

        def fake_spawn(prompt, result_file, config):
            # Child writes its answer to the result file, then the launcher returns.
            Path(result_file).write_text("HELLO_RESULT_123", encoding="utf-8")
            return _DummyProc()

        monkeypatch.setattr(terminal_mod, "spawn_in_terminal", fake_spawn)

        out = _spawn_terminal_agent(
            {"prompt": "say hi", "wait": True, "name": "roundtrip"},
            {"_depth": 0},
        )
        assert "HELLO_RESULT_123" in out

    def test_spawn_no_result_file_times_out(self, monkeypatch):
        from bouzecode.backend.multi_agent import terminal as terminal_mod
        from bouzecode.backend.multi_agent import tools as tools_mod

        def fake_spawn_no_write(prompt, result_file, config):
            # Launcher returns immediately but the child never writes anything.
            return _DummyProc()

        monkeypatch.setattr(terminal_mod, "spawn_in_terminal", fake_spawn_no_write)
        monkeypatch.setattr(tools_mod, "_TERMINAL_WAIT_TIMEOUT", 0.2)
        monkeypatch.setattr(tools_mod, "_TERMINAL_WAIT_INTERVAL", 0.05)

        out = tools_mod._spawn_terminal_agent(
            {"prompt": "silent", "wait": True, "name": "notimeout"},
            {"_depth": 0},
        )
        assert "No result file produced" in out
