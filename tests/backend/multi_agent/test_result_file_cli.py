"""E2E coverage of the CLI's `--result-file` flag.

Moved out of the deleted `test_terminal_subagent.py`: the windowed-spawn path it used
to live next to is gone (sub-agents are now TRACKED subprocesses, see
`multi_agent/tools.py:_spawn_tracked_agent`), but `--result-file` is a plain CLI option
of bouzecode itself and is still supported — so its coverage must not die with the window.
"""
import os
import subprocess
import sys
from pathlib import Path



class TestResultFileCLI:
    """E2E test: --result-file writes output on exit."""

    def test_result_file_written_on_exit(self, tmp_path):
        """Run bouzecode -p with --result-file and verify output is written."""
        from tests.cache_conversation_helpers import require_api_key
        require_api_key()  # live gateway test — skips off VPN instead of hanging 90s
        result_file = tmp_path / "agent_result.txt"
        cmd = [
            sys.executable, "-m", "bouzecode",
            "-p", "Close with FinalAnswer, answer exactly: RESULT_FILE_TEST_OK_789",  # -p: only FinalAnswer delivers
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
