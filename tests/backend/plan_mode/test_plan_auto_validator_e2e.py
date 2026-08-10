# [desc] E2E tests verifying plan auto-validator verdicts (approve/reject) affect WritePlan outcomes in conversations [/desc]
"""Auto-validator verdict observed through real bouzecode() conversations.

The validator's *parsing* (_parse_verdict, XML formats, truncation) and its
override/state-payload plumbing are pure functions the harness cannot reach
through a conversation — they stay as units (test_plan_auto_validator.py,
test_plan_auto_validator_xml.py). What a conversation *can* observe is the
verdict's effect: an approved WritePlan records the plan and unblocks the next
Write; a rejected one returns the feedback and leaves writes plan-gated. We
inject the verdict via the _plan_auto_validate_result config override (the same
seam the production override uses), so no validator LLM call is made.
"""
from __future__ import annotations


import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.core.tool_registry import enable_tool

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


@pytest.fixture(autouse=True)
def _enable_plan_tools():
    enable_tool("EnterPlanMode")
    enable_tool("ExitPlanMode")


def _writeplan(tid="p1"):
    return ('<tool_use name="WritePlan" id="' + tid + '"><param name="content">'
            '# Plan\n## Tests\nwrite a failing test first</param></tool_use>')


def _write(path, tid="w1"):
    return (f'<tool_use name="Write" id="{tid}"><param name="file_path">{path}</param>'
            f'<param name="content">x</param></tool_use>')


def _results(result, name):
    return [m["content"] for m in result.messages
            if m.get("role") == "tool" and m.get("name") == name]


@pytest.fixture(autouse=True)
def _plans_in_a_private_cwd(tmp_path_factory, monkeypatch):
    """`_write_plan` writes to `<cwd>/.nano_claude/plans/<session>.md`, and the
    session id defaults to "default" — so every plan test writes the SAME path.
    Wiping that shared directory was safe sequentially and destructive under
    `-n auto`: one worker deleted the plan another had just written. Giving each
    test its own cwd removes the shared path instead of racing on it."""
    monkeypatch.chdir(tmp_path_factory.mktemp("plan_cwd"))


def test_approved_plan_unblocks_following_write(tmp_path):
    # WritePlan and the Write must be in separate batches: the plan is recorded
    # only after WritePlan executes, so the gated Write happens the turn after.
    f = tmp_path / "feature.py"
    mock = MockLLM([
        f"{METH}\n{_writeplan()}",
        f"{METH}\n{_write(f)}",
        # Closing turn = plain text, no tool call. A turn carrying only a
        # Methodology counts as "neither work nor final answer": the engine
        # answers with a continue nudge and asks for one more turn.
        "done.",
    ])
    result = bouzecode(["plan and build"], mock_llm=mock,
                       config_overrides={"_plan_auto_validate_result": (True, "")})
    assert "Plan saved" in _results(result, "WritePlan")[0]
    assert "PLAN REQUIRED" not in _results(result, "Write")[0]
    assert f.exists()


def test_rejected_plan_returns_feedback(tmp_path):
    """A rejected plan surfaces the validator feedback in the tool result.
    (The old 'keeps writes blocked' half is gone: WritePlan is advisory now —
    the hard plan gate was removed by design.)"""
    f = tmp_path / "feature.py"
    mock = MockLLM([
        f"{METH}\n{_writeplan()}\n{_write(f)}",
        "recover.",
    ])
    result = bouzecode(["plan and build"], mock_llm=mock,
                       config_overrides={"_plan_auto_validate_result": (False, "No failing test first")})
    plan_out = _results(result, "WritePlan")[0]
    # Wording of the cancellation line is the engine's ("Cancelled: plan rejected
    # by user — ..."); what this test pins is that the refusal is visible AND that
    # the validator's own reason is carried through to the model, tagged.
    assert "plan rejected" in plan_out.lower()
    assert "[Auto-validator] No failing test first" in plan_out
