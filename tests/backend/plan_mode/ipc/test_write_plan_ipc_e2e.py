# [desc] Conversation feature tests for WritePlan IPC: plan.md written and accumulated, empty plan rejected, user_validation_required parks the agent in awaiting_plan_validation. [/desc]
"""WritePlan IPC behaviour observed through real bouzecode() conversations.

Replaces test_write_plan_ipc.py and the WritePlan half of test_plan_validation_ipc.py:
when the agent runs under the web UI (`_web_agent_dir` set), a WritePlan call
writes plan.md next to the agent's IPC state, several plans in one turn are
concatenated with a '---' separator, an empty plan is refused, and a plan flagged
`user_validation_required` parks the agent on `awaiting_plan_validation` so the
user is asked to approve it.

Plans accumulate per agent process: `_all_plans` lives on the config the loop
carries, so accumulation is observable within a run, not across two independent
`bouzecode()` calls.

NOT covered here: the terminal variant of plan validation, which reads the
user's answer from real stdin (pytest captures it) instead of pausing the loop.
It stays a unit test in test_plan_validation_ipc.py.
"""
from __future__ import annotations

import json

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'

# WritePlan runs the plan auto-validator (an LLM call) before writing anything.
# `_plan_auto_validate_result` is the production override read first by
# `validate_plan_auto`; injecting an approval here keeps these tests on the IPC
# behaviour they are about instead of reaching the real API.
_APPROVED_PLAN = {"_plan_auto_validate_result": (True, "")}


def _writeplan(content, tid="p1", validate=False):
    extra = ('<param name="user_validation_required">true</param>' if validate else "")
    return (f'<tool_use name="WritePlan" id="{tid}">'
            f'<param name="content">{content}</param>{extra}</tool_use>')


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


def test_writeplan_writes_plan_md_next_to_the_agent(tmp_path):
    """A plan written by an agent running in the web UI shows up as plan.md."""
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    writeplan_call = _writeplan("# Test Plan\\n\\nStep 1")
    mock = MockLLM([f"{METH}\n{writeplan_call}", "done."])
    result = bouzecode(["plan it"], mock_llm=mock,
                       config_overrides={"_web_agent_dir": str(ipc), **_APPROVED_PLAN})
    assert "Plan saved" in _results(result, "WritePlan")[0]
    plan_md = ipc / "plan.md"
    assert plan_md.exists()
    assert "Test Plan" in plan_md.read_text(encoding="utf-8")


def test_several_plans_are_appended_not_overwritten(tmp_path):
    """Writing a second plan keeps the first one — they stack, separated by '---'."""
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    mock = MockLLM([
        f"{METH}\n{_writeplan('# Plan A', 'p1')}\n{_writeplan('# Plan B', 'p2')}",
        "done.",
    ])
    bouzecode(["two plans"], mock_llm=mock,
              config_overrides={"_web_agent_dir": str(ipc), **_APPROVED_PLAN})
    text = (ipc / "plan.md").read_text(encoding="utf-8")
    assert "Plan A" in text and "Plan B" in text
    assert "---" in text


def test_empty_plan_content_rejected():
    """An empty plan is refused rather than written out."""
    mock = MockLLM([f"{METH}\n{_writeplan('   ')}", "done."])
    result = bouzecode(["empty plan"], mock_llm=mock)
    assert "empty" in _results(result, "WritePlan")[0].lower()


def test_plan_needing_validation_parks_the_agent_until_the_user_approves(
    tmp_path, monkeypatch
):
    """A plan flagged user_validation_required parks the agent on
    'awaiting_plan_validation'; the user answers '1' and the agent carries on."""
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    monkeypatch.setattr(
        "bouzecode.backend.tools.interaction.is_web_ipc_active", lambda: True
    )
    mock = MockLLM([f"{METH}\n{_writeplan('# Gated Plan', validate=True)}", "done."])
    result = bouzecode(["plan and ask me"], mock_llm=mock,
                       replies=["1"],
                       config_overrides={"_web_agent_dir": str(ipc)})

    assert "Awaiting user validation" in _results(result, "WritePlan")[0]
    state = json.loads((ipc / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "awaiting_plan_validation"
