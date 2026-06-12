# [desc] E2E tests verifying RunPythonTest tool's pass/fail summary appears in conversation tool_result output. [/desc]
"""RunPythonTest pass/fail summary observed through a real bouzecode() conversation.

Replaces the two direct-call cases in test_test_runner_progress.py
(TestRunPythonTestProgress: "3 passed", "1 failed"/"1 passed"). The pass/fail
summary is conversation-observable — it lands in the [RunPythonTest] tool_result
the loop produces — so we exercise it through the (mocked) model emitting the
tool call instead of calling run_python_test() directly.

The regex internals (TestProgressRegexes) and the tqdm stderr progress bar are
NOT conversation-observable (tqdm writes to stderr, never to the tool_result),
so they stay as units in test_test_runner_progress.py / test_tqdm_progress_e2e.py.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM


@pytest.fixture(autouse=True)
def _enable_rpt():
    from bouzecode.backend.core.tool_registry import enable_tool
    enable_tool("RunPythonTest")


METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _runtest(target, tid="rpt1"):
    return (f'<tool_use name="RunPythonTest" id="{tid}">'
            f'<param name="targets">["{target}"]</param>'
            f'<param name="parallel">off</param>'
            f'<param name="no_sync">true</param></tool_use>')


def _runner_result(result):
    for m in result.messages:
        if m.get("role") == "tool" and isinstance(m.get("content"), str) \
                and "[RunPythonTest]" in m["content"]:
            return m["content"]
    raise AssertionError("RunPythonTest tool_result not found")


def test_all_passing_summary_in_tool_result(tmp_path):
    f = tmp_path / "test_mini.py"
    f.write_text(
        "def test_one(): assert True\n"
        "def test_two(): assert True\n"
        "def test_three(): assert True\n",
        encoding="utf-8",
    )
    target = str(f).replace("\\", "/")
    mock = MockLLM([f"{METH}\n{_runtest(target)}", f"done.\n{METH}"])
    result = bouzecode(["run the tests"], mock_llm=mock)
    assert "3 passed" in _runner_result(result)


def test_failure_summary_in_tool_result(tmp_path):
    f = tmp_path / "test_fail.py"
    f.write_text(
        "def test_ok(): assert True\n"
        "def test_bad(): assert False\n",
        encoding="utf-8",
    )
    target = str(f).replace("\\", "/")
    mock = MockLLM([f"{METH}\n{_runtest(target)}", f"done.\n{METH}"])
    result = bouzecode(["run the tests"], mock_llm=mock)
    out = _runner_result(result)
    assert "1 failed" in out
    assert "1 passed" in out
