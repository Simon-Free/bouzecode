# [desc] E2E test verifying that Write tool is allowed after an approved WritePlan (no PLAN REQUIRED gate).
# <tool_use name="FinalAnswer" id="f1"><param name="answer">E2E test verifying that Write tool is allowed after an approved WritePlan (no PLAN REQUIRED gate).</param></tool_use> [/desc]
"""E2E test around the WritePlan auto-validator verdict.

The old test_edit_blocked_after_plan_rejected_by_auto_validator was removed:
it pinned the hard PLAN REQUIRED gate, which is gone by design (WritePlan is
advisory — registration.py). The rejected-plan feedback path is covered by
plan_mode/test_plan_auto_validator_e2e.py::test_rejected_plan_returns_feedback.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.core.tool_registry import enable_tool


@pytest.fixture(autouse=True)
def _enable_plan_tools():
    enable_tool("EnterPlanMode")
    enable_tool("ExitPlanMode")


def test_edit_allowed_after_plan_approved():
    """Regression: WritePlan approved → Edit should pass."""
    mock = MockLLM([
        # Turn 1: Methodology + WritePlan (approved)
        '<tool_use name="Methodology" id="m1">'
        '<param name="content">Planning to edit main.py</param>'
        '</tool_use>'
        '<tool_use name="WritePlan" id="p1">'
        '<param name="content"># Plan\n\nEdit main.py with proper tests</param>'
        '</tool_use>',
        # Turn 2: Methodology + Write (should pass)
        '<tool_use name="Methodology" id="m2">'
        '<param name="content">Implementing plan</param>'
        '</tool_use>'
        '<tool_use name="Write" id="w1">'
        '<param name="file_path">main.py</param>'
        '<param name="content">print("hello")</param>'
        '</tool_use>',
        # Turn 3: final reply — Methodology every turn (else enforcement adds a turn)
        'Done.\n<tool_use name="Methodology" id="m3">'
        '<param name="content">Done</param></tool_use>',
    ])

    result = bouzecode(
        messages=["Write main.py"],
        mock_llm=mock,
        config_overrides={"_plan_auto_validate_result": (True, ""), "enforce_tests": False},
    )

    # Write should NOT be blocked
    write_blocked = [
        msg for msg in result.messages
        if msg.get("role") == "tool" and msg.get("name") == "Write"
        and "PLAN REQUIRED" in str(msg.get("content", ""))
    ]
    assert len(write_blocked) == 0, (
        f"Write after approved plan should not be blocked. Got: {write_blocked}"
    )
