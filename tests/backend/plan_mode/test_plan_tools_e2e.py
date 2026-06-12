# [desc] Conversation feature tests for EnterPlanMode/ExitPlanMode tools: activation, idempotency, exit echo, and error paths
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Conversation feature tests for EnterPlanMode/ExitPlanMode tools: activation, idempotency, exit echo, and error paths</param></tool_use> [/desc]
"""EnterPlanMode / ExitPlanMode observed through real bouzecode() conversations.

Replaces the direct-call test_plan_tools.py for everything observable from a
conversation: the tool *results* (mode-activation message, "Already in plan
mode", empty-plan rejection, "Not in plan mode", plan content echoed on exit).

The permission-gating part of test_plan_tools.py (Step 3: _check_permission
blocks Writes while in plan mode) is NOT observable here — the harness stubs
_check_permission to always-true when a mock LLM is wired — and the
system-prompt assertion (Step 8) is a static-config invariant. Both stay as a
trimmed unit (test_plan_tools.py).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.core.tool_registry import enable_tool

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


@pytest.fixture(autouse=True)
def _enable_plan_tools():
    enable_tool("EnterPlanMode")
    enable_tool("ExitPlanMode")


def _enter(desc="Add WebSocket support", tid="e1"):
    return (f'<tool_use name="EnterPlanMode" id="{tid}">'
            f'<param name="task_description">{desc}</param></tool_use>')


def _exit(tid="x1"):
    return f'<tool_use name="ExitPlanMode" id="{tid}"></tool_use>'


def _results(result, name):
    return [m["content"] for m in result.messages
            if m.get("role") == "tool" and m.get("name") == name]


@pytest.fixture(autouse=True)
def _clean_plans():
    yield
    shutil.rmtree(Path.cwd() / ".nano_claude" / "plans", ignore_errors=True)


def test_enter_plan_mode_activates_and_creates_plan_file():
    mock = MockLLM([f"{METH}\n{_enter()}", f"done.\n{METH}"])
    result = bouzecode(["start planning"], mock_llm=mock)
    out = _results(result, "EnterPlanMode")[0]
    assert "Plan mode activated" in out
    assert ".nano_claude" in out  # references the created plan file
    plan_file = Path.cwd() / ".nano_claude" / "plans" / "default.md"
    assert plan_file.exists()
    assert "WebSocket" in plan_file.read_text(encoding="utf-8")


def test_enter_twice_is_idempotent():
    mock = MockLLM([
        f"{METH}\n{_enter()}",
        f'{METH}\n{_enter(desc="", tid="e2")}',
        f"done.\n{METH}",
    ])
    result = bouzecode(["plan"], mock_llm=mock)
    outs = _results(result, "EnterPlanMode")
    assert "Plan mode activated" in outs[0]
    assert "Already in plan mode" in outs[1]


def test_exit_echoes_plan_content_and_restores_mode():
    # The auto-created header "# Plan: Add WebSocket support" is non-empty plan
    # content, so ExitPlanMode succeeds and echoes it.
    mock = MockLLM([
        f"{METH}\n{_enter()}",
        f"{METH}\n{_exit()}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["plan then exit"], mock_llm=mock)
    out = _results(result, "ExitPlanMode")[0]
    assert "Plan mode exited" in out
    assert "Wait for the user to approve" in out
    assert "Add WebSocket support" in out  # plan content echoed back


def test_exit_with_empty_plan_is_rejected():
    # EnterPlanMode with no task_description writes just "# Plan\n\n"; that strips
    # to "# Plan", which ExitPlanMode treats as empty → stays in plan mode.
    mock = MockLLM([
        f'{METH}\n{_enter(desc="")}',
        f"{METH}\n{_exit()}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["plan empty"], mock_llm=mock)
    out = _results(result, "ExitPlanMode")[0]
    assert "empty" in out.lower()


def test_exit_without_enter_reports_not_in_plan_mode():
    mock = MockLLM([f"{METH}\n{_exit()}", f"done.\n{METH}"])
    result = bouzecode(["exit without entering"], mock_llm=mock)
    out = _results(result, "ExitPlanMode")[0]
    assert "Not in plan mode" in out
