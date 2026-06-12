# [desc] Tests RunPythonTest progress bar regex parsing and end-to-end test execution reporting [/desc]
"""Tests for RunPythonTest streaming progress bar."""
import re
from pathlib import Path

import pytest
from bouzecode.backend.tools.ops.test_runner import run_python_test, _COLLECTED_RE, _XDIST_COLLECTED_RE, _XDIST_RESULT_RE, _STANDARD_RESULT_RE


class TestProgressRegexes:
    """Unit tests for the regex patterns used in progress parsing."""

    def test_collected_items(self):
        assert _COLLECTED_RE.search("collected 42 items").group(1) == "42"
        assert _COLLECTED_RE.search("collected 1 item").group(1) == "1"
        assert _COLLECTED_RE.search("random line") is None

    def test_xdist_collected_items(self):
        assert _XDIST_COLLECTED_RE.search("5 workers [5 items]").group(1) == "5"
        assert _XDIST_COLLECTED_RE.search("1 worker [1 item]").group(1) == "1"
        assert _XDIST_COLLECTED_RE.search("random line") is None

    def test_xdist_result(self):
        m = _XDIST_RESULT_RE.match("[gw0] PASSED tests/test_foo.py::test_bar")
        assert m and m.group(1) == "PASSED"
        m = _XDIST_RESULT_RE.match("[gw3] FAILED tests/test_x.py::test_y")
        assert m and m.group(1) == "FAILED"
        assert _XDIST_RESULT_RE.match("some other line") is None

    def test_standard_result(self):
        m = _STANDARD_RESULT_RE.search("tests/test_foo.py::test_bar PASSED")
        assert m and m.group(1) == "PASSED"
        m = _STANDARD_RESULT_RE.search("tests/test_x.py::test_y FAILED")
        assert m and m.group(1) == "FAILED"
        # Verbose mode with percentage
        m = _STANDARD_RESULT_RE.search("tests/test_foo.py::test_bar PASSED                    [ 20%]")
        assert m and m.group(1) == "PASSED"
        assert _STANDARD_RESULT_RE.search("collecting ...") is None


class TestRunPythonTestProgress:
    """E2E: run real mini-tests and verify output includes pass counts."""

    def test_runs_simple_tests_and_reports(self, tmp_path):
        test_file = tmp_path / "test_mini.py"
        test_file.write_text(
            "def test_one(): assert True\n"
            "def test_two(): assert True\n"
            "def test_three(): assert True\n"
        )
        result = run_python_test(
            targets=[str(test_file)],
            parallel="off",
            timeout=60,
            no_sync=True,
        )
        assert "3 passed" in result

    def test_reports_failures(self, tmp_path):
        test_file = tmp_path / "test_fail.py"
        test_file.write_text(
            "def test_ok(): assert True\n"
            "def test_bad(): assert False\n"
        )
        result = run_python_test(
            targets=[str(test_file)],
            parallel="off",
            timeout=60,
            no_sync=True,
        )
        assert "1 failed" in result
        assert "1 passed" in result
