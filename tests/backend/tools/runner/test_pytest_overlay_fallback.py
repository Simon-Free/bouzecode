"""RunPythonTest must survive a resolved env where pytest is not installed.

Real-world symptom (2026-08-24): on a venv SHARED between the server and the
agents, `Scripts/pytest.exe` survives an old install while the module is gone.
`uv run pytest` starts the shim and dies on `import _pytest`, and the agent got a
raw traceback with nothing to act on.

The fix retries ONCE through `uv run --with pytest --with pytest-xdist`, an
ephemeral overlay in the uv cache that never writes to the shared venv.
"""

from bouzecode.backend.tools.ops.test_runner import (
    _looks_like_missing_pytest,
    _missing_pytest_help,
    _with_pytest_overlay,
)

from pathlib import Path

# Verbatim stderr captured from `uv run --no-sync --directory <worktree> pytest --version`
REAL_FAILURE = """Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "c:\\users\\x\\bouzecode\\.venv\\Scripts\\pytest.exe\\__main__.py", line 4, in <module>
ModuleNotFoundError: No module named '_pytest'"""


class TestDetection:
    def test_real_missing_pytest_traceback_is_detected(self):
        assert _looks_like_missing_pytest(REAL_FAILURE) is True

    def test_missing_pytest_top_level_module_is_detected(self):
        assert _looks_like_missing_pytest("ModuleNotFoundError: No module named 'pytest'") is True

    def test_normal_green_run_is_not_detected(self):
        out = "===== test session starts =====\ncollected 3 items\n3 passed in 0.4s"
        assert _looks_like_missing_pytest(out) is False

    def test_pytest_that_started_is_never_retried(self):
        """A test asserting on that very message must not trigger a second run."""
        out = (
            "===== test session starts =====\n"
            "FAILED tests/test_x.py - ModuleNotFoundError: No module named 'pytest'\n"
            "1 failed in 0.2s"
        )
        assert _looks_like_missing_pytest(out) is False


class TestOverlay:
    def test_with_flags_are_inserted_right_after_uv_run(self):
        cmd = ["uv", "run", "--no-sync", "--directory", "/repo", "pytest", "-v"]
        assert _with_pytest_overlay(cmd) == [
            "uv",
            "run",
            "--with",
            "pytest",
            "--with",
            "pytest-xdist",
            "--no-sync",
            "--directory",
            "/repo",
            "pytest",
            "-v",
        ]

    def test_xdist_is_provided_too(self):
        """parallel != off adds -n, which needs pytest-xdist in the overlay."""
        overlaid = _with_pytest_overlay(["uv", "run", "pytest", "-n", "4"])
        assert "pytest-xdist" in overlaid

    def test_original_command_is_not_mutated(self):
        cmd = ["uv", "run", "pytest"]
        _with_pytest_overlay(cmd)
        assert cmd == ["uv", "run", "pytest"]

    def test_overlay_is_idempotent_so_no_retry_loop(self):
        cmd = ["uv", "run", "--with", "pytest", "pytest"]
        assert _with_pytest_overlay(cmd) == cmd

    def test_overlay_never_asks_uv_to_sync(self):
        overlaid = _with_pytest_overlay(["uv", "run", "--no-sync", "pytest"])
        assert "sync" not in [p for p in overlaid if p != "--no-sync"]
        assert "--no-sync" in overlaid


class TestActionableHelp:
    def test_help_names_the_throwaway_venv_and_forbids_uv_sync(self):
        msg = _missing_pytest_help(Path("/repo"), "uv run pytest", REAL_FAILURE)
        assert msg.startswith("Error:")
        assert ".venv-test" in msg
        assert "uv venv" in msg
        assert "NEVER run `uv sync`" in msg

    def test_help_keeps_the_tail_of_the_real_output(self):
        msg = _missing_pytest_help(Path("/repo"), "uv run pytest", REAL_FAILURE)
        assert "No module named '_pytest'" in msg
