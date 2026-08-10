# [desc] Unit tests for the two plan-validation cases a conversation cannot reach: the terminal prompt (real stdin) and how the web UI files a parked agent. [/desc]
"""Plan validation — the two cases no bouzecode() conversation can produce.

Everything a conversation CAN show (plan.md written, plans accumulated, empty
plan rejected, agent parked on `awaiting_plan_validation`) lives in
test_write_plan_ipc_e2e.py. Two cases stay here:

1. **Terminal validation** reads the user's answer from real stdin, which pytest
   captures — the harness's `replies` queue only feeds the *loop's* pause, and
   that pause exists only under web IPC. Only a direct call with the prompt
   stubbed can prove the terminal path asks the user and writes no IPC state.
2. **Agent categorisation** (`_agent_category`) is what the web UI's agent list
   reads to put an agent in the "awaiting" column. It is a pure function of the
   IPC status of an already-running agent process, not of a conversation.
"""
from unittest.mock import patch

import pytest


def test_terminal_plan_validation_asks_the_user_and_writes_no_ipc_state(tmp_path):
    """In the terminal, a plan needing validation is approved by the user's answer
    directly — nothing is filed in the IPC state the web UI watches."""
    from bouzecode.backend.tools.plan_mode import _write_plan

    ipc_dir = tmp_path / "ipc"
    ipc_dir.mkdir()
    config = {
        "_plan_dir": str(tmp_path / "plans"),
        "_web_agent_dir": str(ipc_dir),
        "_context_state": None,
    }

    with patch("bouzecode.backend.tools.interaction.is_web_ipc_active", return_value=False):
        with patch("bouzecode.backend.tools.interaction._ask_user_question",
                   return_value="1"):
            result = _write_plan(
                {"content": "# Plan", "user_validation_required": True}, config
            )

    assert "validated" in result.lower()
    assert not (ipc_dir / "state.json").exists()


def test_terminal_plan_validation_rejects_on_a_negative_answer(tmp_path):
    """Answering anything other than the approval choice rejects the plan
    instead of silently recording it."""
    from bouzecode.backend.tools.plan_mode import _write_plan, PlanRejected

    config = {"_plan_dir": str(tmp_path / "plans"), "_context_state": None}

    with patch("bouzecode.backend.tools.interaction.is_web_ipc_active", return_value=False):
        with patch("bouzecode.backend.tools.interaction._ask_user_question",
                   return_value="Non, ça ne me va pas"):
            with pytest.raises(PlanRejected):
                _write_plan({"content": "# Plan", "user_validation_required": True}, config)


class _FakeAgent:
    agent_id = "test"
    session_path = None
    started_at = ""
    finished_at = None
    prompt = "test"
    model = "test"
    pid = None


def test_agent_awaiting_plan_validation_shows_in_the_awaiting_column():
    """An agent parked on a plan the user has not approved yet is listed as
    'awaiting', not as running or finished."""
    from bouzecode.web_v2.runtime.state_streams import _agent_category
    from bouzecode.web_v2.runtime import runner

    with patch.object(runner, "get_ipc_state",
                      return_value={"status": "awaiting_plan_validation"}):
        with patch.object(runner, "is_running", return_value=True):
            assert _agent_category(_FakeAgent()) == "awaiting"


def test_agent_awaiting_a_question_also_shows_in_the_awaiting_column():
    """The same column holds an agent blocked on AskUserQuestion."""
    from bouzecode.web_v2.runtime.state_streams import _agent_category
    from bouzecode.web_v2.runtime import runner

    with patch.object(runner, "get_ipc_state", return_value={"status": "awaiting_input"}):
        with patch.object(runner, "is_running", return_value=True):
            assert _agent_category(_FakeAgent()) == "awaiting"
