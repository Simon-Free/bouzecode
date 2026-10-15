# [desc] E2E tests for RunPythonTest tool: direct function calls and real LLM pipeline integration [/desc]
"""E2E tests for the RunPythonTest tool.

Tests:
1. Direct call to run_python_test() on a trivial test file
2. Real LLM pipeline integration — model uses RunPythonTest through actual XML parsing
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bouzecode.backend.tools.ops.test_runner import run_python_test
from tests.e2e_harness import bouzecode
from tests.cache_conversation_helpers import require_api_key

# Chemins ABSOLUS : le conftest du répertoire place chaque test dans son tmp_path (cwd), pour
# que le pytest imbriqué y reste. RunPythonTest remonte de la cible au pyproject du dépôt.
REPO = Path(__file__).resolve().parents[4]
TRIVIAL = (REPO / "tests" / "test_trivial_runner.py").as_posix()
TRIVIAL_SLOW = (REPO / "tests" / "test_trivial_runner_slow.py").as_posix()
ABSENT = (REPO / "tests" / "does_not_exist_xyz.py").as_posix()


class TestRunPythonTestDirect:
    """Direct calls to run_python_test() function."""

    def test_single_file_passes(self):
        """Run a trivial test file; show=['passed'] lists the tests that passed."""
        result = run_python_test(
            targets=[TRIVIAL],
            parallel="off",
            timeout=60,
            no_sync=True,
            show=["passed"],
        )
        assert "[RunPythonTest]" in result
        assert "passed" in result.lower()
        assert "test_always_passes" in result

    def test_no_targets_with_full_runs_all(self, monkeypatch):
        """No targets + full=True: the whole project suite is collected."""
        # Le sujet EST la suite du dépôt : le cwd y revient (basetemp et cache restent
        # détournés par le conftest).
        monkeypatch.chdir(REPO)
        monkeypatch.setenv("BZ_NIGHTLY", "1")  # full=true : réservé au build nightly
        result = run_python_test(
            targets=None,
            parallel="off",
            timeout=120,
            extra_args=["--co", "-q"],  # collect-only, just list tests
            no_sync=True,
            full=True,
        )
        assert "[RunPythonTest]" in result
        assert "test" in result.lower()

    def test_keyword_filter(self):
        """Keyword filter selects specific tests."""
        result = run_python_test(
            targets=[TRIVIAL],
            parallel="off",
            keyword="always_passes",
            timeout=60,
            no_sync=True,
            show=["passed"],
        )
        assert "passed" in result.lower()
        assert "test_always_passes" in result

    def test_parallel_numeric(self):
        """Parallel='2' adds -n 2 to the command and the run passes."""
        result = run_python_test(
            targets=[TRIVIAL],
            parallel="2",
            timeout=60,
            no_sync=True,
        )
        assert "-n 2" in result
        assert "passed" in result.lower()

    def test_nonexistent_file(self):
        """Nonexistent target produces error in output."""
        result = run_python_test(
            targets=[ABSENT],
            parallel="off",
            timeout=30,
            no_sync=True,
        )
        assert "error" in result.lower() or "no such file" in result.lower()

    def test_marker_filter(self):
        """Marker filter selects only tests with that marker."""
        result = run_python_test(
            targets=[TRIVIAL_SLOW],
            parallel="off",
            marker="slow",
            timeout=5,
            extra_args=["--co"],  # collect-only to avoid actually sleeping
            no_sync=True,
        )
        assert "test_slow_operation" in result
        assert "[RunPythonTest]" in result

    def test_timeout_kills_process(self):
        """Timeout produces error message and kills the process."""
        result = run_python_test(
            targets=[TRIVIAL_SLOW],
            parallel="off",
            marker="slow",
            timeout=3,
            no_sync=True,
        )
        assert "timed out" in result.lower()
        assert "3s" in result

    def test_extra_args_passed(self):
        """Extra args are forwarded to pytest."""
        result = run_python_test(
            targets=[TRIVIAL],
            parallel="off",
            extra_args=["--tb=line"],
            timeout=60,
            no_sync=True,
        )
        assert "passed" in result.lower()
        assert "[RunPythonTest]" in result

    def test_output_format_header(self):
        """Output starts with [RunPythonTest] header, cwd, and command."""
        result = run_python_test(
            targets=[TRIVIAL],
            parallel="off",
            timeout=60,
            no_sync=True,
        )
        lines = result.splitlines()
        assert lines[0].startswith("[RunPythonTest] cwd=")
        assert lines[1].startswith("$ ")
        assert "pytest" in lines[1]
        assert "─" * 10 in lines[2]


class TestRunPythonTestMockPipeline:
    """Deterministic pipeline tests using MockLLM — no real LLM calls."""

    @pytest.fixture(autouse=True)
    def _enable_rpt(self):
        from bouzecode.backend.core.tool_registry import enable_tool
        enable_tool("RunPythonTest")

    def test_mock_llm_calls_tool(self):
        """MockLLM emits RunPythonTest XML, tool executes, result in messages."""
        from tests.fake_llm import MockLLM

        mock = MockLLM([
            # Turn 1: model calls Methodology (enforcement) + RunPythonTest
            '<tool_use name="Methodology" id="m1"><param name="content">Running tests</param></tool_use>'
            '<tool_use name="RunPythonTest" id="rpt1">'
            f'<param name="targets">["{TRIVIAL}"]</param>'
            '<param name="parallel">off</param>'
            '<param name="no_sync">true</param>'
            '</tool_use>',
            # Turn 2: plain text, no tool call — that is what closes a session.
            # A Methodology-only batch is bookkeeping and earns a continue-nudge.
            "The tests passed successfully.",
        ])
        result = bouzecode(
            messages=["Run the trivial tests"],
            mock_llm=mock,
        )
        assert "passed" in result.last_reply.lower() or "passed" in str(result.messages).lower()

        # Verify RunPythonTest was actually executed (tool_result in messages)
        found = False
        for msg in result.messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            # Format 1: role="tool" with string content
            if role == "tool" and isinstance(content, str) and "[RunPythonTest]" in content:
                found = True
                break
            # Format 2: role="user" with tool_result blocks
            if role == "user" and isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        rc = block.get("content", "")
                        text = rc if isinstance(rc, str) else " ".join(
                            str(sub.get("text", "")) for sub in rc if isinstance(sub, dict)
                        )
                        if "[RunPythonTest]" in text:
                            found = True
                            break
            if found:
                break
        assert found, "RunPythonTest tool_result not found in conversation messages"


class TestRunPythonTestPipeline:
    """Real LLM integration — RunPythonTest called through actual XML parsing."""

    @pytest.fixture(autouse=True)
    def _enable_rpt(self):
        # RunPythonTest left the default whitelist; without this the live model
        # improvises with Bash and the asserted tool_result never appears.
        from bouzecode.backend.core.tool_registry import enable_tool
        enable_tool("RunPythonTest")

    def test_real_llm_runs_test(self):
        """Real LLM receives prompt, calls RunPythonTest, confirms tests passed."""
        require_api_key()
        result = bouzecode(messages=[
            f"Use the RunPythonTest tool to run {TRIVIAL} with parallel='off' and no_sync=true. "
            "Report whether the tests passed or failed."
        ])
        # The LLM should have used RunPythonTest and reported success
        assert "passed" in result.last_reply.lower() or "pass" in result.last_reply.lower()

        # Verify RunPythonTest tool_result exists in the conversation. Tool
        # results are stored as role="tool" messages (XML protocol); older
        # Anthropic-native runs used role="user" with tool_result blocks — accept
        # both formats.
        found_tool_result = False
        for msg in result.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "tool" and isinstance(content, str):
                if "[RunPythonTest]" in content and "passed" in content.lower():
                    found_tool_result = True
            elif role == "user" and isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        rc = block.get("content", "")
                        text = (
                            " ".join(str(sub.get("text", "")) for sub in rc)
                            if isinstance(rc, list) else str(rc)
                        )
                        if "[RunPythonTest]" in text and "passed" in text.lower():
                            found_tool_result = True
        assert found_tool_result, "RunPythonTest tool_result with 'passed' not found in messages"
