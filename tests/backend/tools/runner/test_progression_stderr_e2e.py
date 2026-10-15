# [desc] E2E : sans spinner (agent web, CLI non interactif), la progression de RunPythonTest s'ecrit en direct sur stderr (ligne reecrite par \r) [/desc]
"""E2E test: the progress line actually updates during test execution.

The fix (PYTHONUNBUFFERED=1 + bufsize=1) ensures pytest output is line-buffered,
so the progress is tracked in real time instead of staying at 0%.

These tests used to `importorskip("tqdm")`: tqdm left the venv with openai 3 (2026-10-05)
and they skipped silently while the progress had vanished. No optional dependency now
(progression_terminal.LigneProgression): they always run.
"""
import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bouzecode.backend.tools.ops.test_runner import run_python_test


@pytest.fixture
def multi_test_file(tmp_path):
    """Create a test file with 5 simple tests."""
    test_file = tmp_path / "test_five.py"
    test_file.write_text(
        "def test_a(): assert True\n"
        "def test_b(): assert True\n"
        "def test_c(): assert True\n"
        "def test_d(): assert True\n"
        "def test_e(): assert True\n"
    )
    return test_file


class TestTqdmProgressUpdates:
    """Verify tqdm progress bar receives updates during pytest execution."""

    def test_progress_bar_reaches_completion_standard(self, multi_test_file):
        """Standard mode (no xdist): tqdm bar shows 5/5 on stderr."""
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            result = run_python_test(
                targets=[str(multi_test_file)],
                parallel="off",
                timeout=60,
                no_sync=True,
            )
        finally:
            sys.stderr = old_stderr

        stderr_output = captured.getvalue()

        # Verify tests actually passed
        assert "5 passed" in result

        # Verify tqdm wrote progress updates to stderr
        # tqdm uses \r to overwrite — the final state should show 5/5
        assert "5/5" in stderr_output, (
            f"tqdm did not reach 5/5. stderr was:\n{stderr_output!r}"
        )
        # Verify the postfix shows passed count
        assert "✅5" in stderr_output or "✅ 5" in stderr_output, (
            f"tqdm postfix missing pass count. stderr was:\n{stderr_output!r}"
        )

    @pytest.mark.skipif(
        os.environ.get("PYTEST_XDIST_WORKER") is not None,
        reason="nested xdist: spawning an inner `pytest -n 2` from within an "
        "xdist worker makes the captured tqdm stderr timing-flaky; the same path "
        "is covered serially by test_progress_bar_reaches_completion_standard",
    )
    def test_progress_bar_reaches_completion_xdist(self, multi_test_file):
        """Xdist mode (parallel=2): tqdm bar shows 5/5 on stderr."""
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            result = run_python_test(
                targets=[str(multi_test_file)],
                parallel="2",
                timeout=60,
                no_sync=True,
            )
        finally:
            sys.stderr = old_stderr

        stderr_output = captured.getvalue()

        # Verify tests actually passed
        assert "5 passed" in result

        # Verify tqdm wrote progress updates
        assert "5/5" in stderr_output, (
            f"tqdm did not reach 5/5 in xdist mode. stderr was:\n{stderr_output!r}"
        )

    def test_progress_bar_shows_failures(self, tmp_path):
        """Tqdm postfix shows failure count when tests fail."""
        test_file = tmp_path / "test_mixed.py"
        test_file.write_text(
            "def test_ok1(): assert True\n"
            "def test_ok2(): assert True\n"
            "def test_fail(): assert False\n"
            "def test_ok3(): assert True\n"
        )
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            run_python_test(
                targets=[str(test_file)],
                parallel="off",
                timeout=60,
                no_sync=True,
            )
        finally:
            sys.stderr = old_stderr

        stderr_output = captured.getvalue()

        # Should reach 4/4 total
        assert "4/4" in stderr_output, (
            f"tqdm did not reach 4/4. stderr was:\n{stderr_output!r}"
        )
        # Should show failure in postfix
        assert "❌1" in stderr_output or "❌ 1" in stderr_output, (
            f"tqdm postfix missing failure count. stderr was:\n{stderr_output!r}"
        )

    def test_progress_bar_intermediate_updates(self, multi_test_file):
        """Verify tqdm emits intermediate updates (not just final state).

        With unbuffered output, we should see multiple \r-separated updates,
        proving the bar updates incrementally (not all at once at the end).
        """
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            run_python_test(
                targets=[str(multi_test_file)],
                parallel="off",
                timeout=60,
                no_sync=True,
            )
        finally:
            sys.stderr = old_stderr

        stderr_output = captured.getvalue()

        # tqdm uses \r for line updates — at least 2 means bar was created and updated
        cr_count = stderr_output.count("\r")
        # With very fast tests, tqdm may batch updates: 0% → 100% (2 \r)
        # That still proves the progress mechanism works end-to-end
        assert cr_count >= 2, (
            f"Expected >=2 \\r (bar created + updated), got {cr_count}. "
            f"stderr was:\n{stderr_output!r}"
        )
        # Verify final state shows all tests counted
        assert "5/5" in stderr_output
