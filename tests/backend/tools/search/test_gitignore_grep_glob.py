# [desc] Tests for ignore_gitignore and include_patterns behavior in Grep/Glob tools with mocked ripgrep
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests for ignore_gitignore and include_patterns behavior in Grep/Glob tools with mocked ripgrep</param></tool_use> [/desc]
"""Tests for ignore_gitignore and include_patterns in Grep/Glob tools."""
from unittest.mock import patch
from pathlib import Path

from bouzecode.backend.tools.ops.shell_search import _glob, _grep


class FakeResult:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


def test_glob_ignore_gitignore_true_does_not_add_no_ignore():
    """With ignore_gitignore=True (default), rg should NOT have --no-ignore."""
    with patch("bouzecode.backend.tools.ops.shell_search._has_rg", return_value=True):
        with patch("subprocess.run", return_value=FakeResult("file1.py\nfile2.py")) as mock_run:
            result = _glob("*.py", ".", True, None)
            cmd = mock_run.call_args[0][0]
            assert "--no-ignore" not in cmd
            assert "file1.py" in result


def test_glob_ignore_gitignore_false_adds_no_ignore():
    """With ignore_gitignore=False, rg should have --no-ignore."""
    with patch("bouzecode.backend.tools.ops.shell_search._has_rg", return_value=True):
        with patch("subprocess.run", return_value=FakeResult("file1.py")) as mock_run:
            result = _glob("*.py", ".", False, None)
            cmd = mock_run.call_args[0][0]
            assert "--no-ignore" in cmd


def test_glob_include_patterns_runs_second_pass():
    """With include_patterns, a second rg pass should run with --no-ignore + --glob."""
    call_count = [0]
    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return FakeResult("src/main.py")
        else:
            return FakeResult("data/output.csv")

    with patch("bouzecode.backend.tools.ops.shell_search._has_rg", return_value=True):
        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            result = _glob("**/*", ".", True, ["*.csv"])
            assert mock_run.call_count == 2
            second_cmd = mock_run.call_args_list[1][0][0]
            assert "--no-ignore" in second_cmd
            assert "*.csv" in second_cmd
            assert "data/output.csv" in result
            assert "src/main.py" in result


def test_grep_ignore_gitignore_true_default():
    """With ignore_gitignore=True (default), rg should have --no-require-git but NOT --no-ignore."""
    with patch("bouzecode.backend.tools.ops.shell_search._has_rg", return_value=True):
        with patch("subprocess.run", return_value=FakeResult("file.py:1:match")) as mock_run:
            result = _grep("pattern", ".", None, "content", False, 0, True, None)
            cmd = mock_run.call_args[0][0]
            assert "--no-ignore" not in cmd


def test_grep_ignore_gitignore_false():
    """With ignore_gitignore=False, rg should have --no-ignore."""
    with patch("bouzecode.backend.tools.ops.shell_search._has_rg", return_value=True):
        with patch("subprocess.run", return_value=FakeResult("file.py:1:match")) as mock_run:
            result = _grep("pattern", ".", None, "content", False, 0, False, None)
            cmd = mock_run.call_args[0][0]
            assert "--no-ignore" in cmd


def test_grep_no_path_uses_cwd():
    """When path is None, grep should use cwd instead of returning an error."""
    with patch("bouzecode.backend.tools.ops.shell_search._has_rg", return_value=True):
        with patch("subprocess.run", return_value=FakeResult("file.py:1:hello")) as mock_run:
            result = _grep("hello", None, None, "content", False, 0, True, None)
            assert "Error" not in result
            cmd = mock_run.call_args[0][0]
            # The last element should be cwd (a path string)
            assert cmd[-1] == str(Path.cwd())


def test_grep_include_patterns():
    """With include_patterns, grep should run a second pass and merge results."""
    call_count = [0]
    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return FakeResult("src/main.py:1:data")
        else:
            return FakeResult("data/file.csv:1:data")

    with patch("bouzecode.backend.tools.ops.shell_search._has_rg", return_value=True):
        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            result = _grep("data", ".", None, "content", False, 0, True, ["*.csv"])
            assert mock_run.call_count == 2
            assert "src/main.py:1:data" in result
            assert "data/file.csv:1:data" in result
