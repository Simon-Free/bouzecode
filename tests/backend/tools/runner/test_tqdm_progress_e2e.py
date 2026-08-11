# [desc] The RunPythonTest progress bar: counts pytest lines and renders them on stderr, deterministically. [/desc]
"""What the progress bar owes the user, tested without spawning a real pytest.

The previous version of this file ran `uv run pytest` on a generated test file
inside each test. That measured `uv` and `pytest` far more than it measured
bouzecode, and it lied: under `-n auto` the nested run collided with the outer
one and failed on collection, and on a fresh clone the first `uv run` resolves a
lockfile, blowing the inner timeout and leaving the captured stderr empty. Two
of the four tests failed on a green suite.

Everything bouzecode actually owns lives in `_stream_with_progress`: read the
child's stdout, recognise the "collected N items" line, recognise per-test
result lines (plain and xdist), and drive a tqdm bar on stderr. That is what is
tested here, by feeding it the exact lines pytest prints. Same assertions
(5/5, the pass/fail postfix, incremental `\\r` repaints), milliseconds instead
of two minutes, and no dependency on the machine's load.
"""
import io
import sys

from bouzecode.backend.tools.ops.test_runner import _stream_with_progress


class FakePytestProcess:
    """The bits of `subprocess.Popen` that `_stream_with_progress` consumes."""

    def __init__(self, output_lines):
        self.stdout = iter(line + "\n" for line in output_lines)
        self.pid = -1
        self.returncode = None

    def wait(self):
        self.returncode = 0
        return 0


def _standard_run(passed=5, failed=0):
    """Lines a plain `pytest -v` prints for `passed` + `failed` tests."""
    total = passed + failed
    lines = [f"collected {total} items", ""]
    lines += [f"tests/test_generated.py::test_ok{i} PASSED   [{i}%]"
              for i in range(passed)]
    lines += [f"tests/test_generated.py::test_ko{i} FAILED   [{i}%]"
              for i in range(failed)]
    lines.append(f"===== {passed} passed, {failed} failed =====")
    return lines


def _xdist_run(passed=5):
    lines = [f"4 workers [{passed} items]", ""]
    lines += [f"[gw{i % 4}] PASSED tests/test_generated.py::test_ok{i}"
              for i in range(passed)]
    lines.append(f"===== {passed} passed =====")
    return lines


def _run_capturing_stderr(output_lines):
    """Drive the progress bar over `output_lines`; return (lines, stderr text)."""
    captured = io.StringIO()
    real_stderr = sys.stderr
    sys.stderr = captured
    try:
        lines, timed_out = _stream_with_progress(
            FakePytestProcess(output_lines), timeout=30,
        )
    finally:
        sys.stderr = real_stderr
    assert timed_out is False
    return lines, captured.getvalue()


def test_progress_bar_reaches_completion_standard():
    """Plain pytest output: the bar ends on 5/5 with 5 passes in the postfix."""
    lines, stderr_output = _run_capturing_stderr(_standard_run(passed=5))

    assert "5 passed, 0 failed" in "\n".join(lines)
    assert "5/5" in stderr_output, stderr_output
    assert "✅5" in stderr_output or "✅ 5" in stderr_output, stderr_output


def test_progress_bar_reaches_completion_xdist():
    """`[gw0] PASSED …` lines are counted exactly like plain ones."""
    _, stderr_output = _run_capturing_stderr(_xdist_run(passed=5))

    assert "5/5" in stderr_output, stderr_output


def test_progress_bar_shows_failures():
    """A failing test lands in the ❌ counter, not silently in the ✅ one."""
    _, stderr_output = _run_capturing_stderr(_standard_run(passed=3, failed=1))

    assert "4/4" in stderr_output, stderr_output
    assert "❌1" in stderr_output or "❌ 1" in stderr_output, stderr_output


def test_progress_bar_updates_as_results_arrive():
    """The bar repaints while the run proceeds, it is not drawn once at the end."""
    _, stderr_output = _run_capturing_stderr(_standard_run(passed=5))

    assert stderr_output.count("\r") >= 2, stderr_output
    assert "5/5" in stderr_output


def test_no_progress_bar_when_nothing_was_collected():
    """`collected 0 items` must not open a zero-total bar (tqdm would divide by 0)."""
    lines, stderr_output = _run_capturing_stderr(
        ["collected 0 items", "===== no tests ran ====="]
    )

    assert stderr_output == ""
    assert lines[0] == "collected 0 items"
