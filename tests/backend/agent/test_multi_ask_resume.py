"""Regression tests: multiple AskUserQuestion tool calls in one assistant turn.

Bug: when the model emitted several AskUserQuestion calls in the SAME turn, only
the first was surfaced to the UI. The remaining ones were executed straight-through
on resume, hit the web-IPC safety net (PausedForInput), which was then SWALLOWED by
tool_registry.execute_tool (turned into an "Error executing ..." string) — so the
extra questions were never asked.

Two guarantees are tested here:
1. resume_paused re-applies the AskUserQuestion pre-emption: remaining Ask calls are
   surfaced ONE AT A TIME (a fresh PausedForInput per question) instead of executed.
2. execute_tool PROPAGATES control-flow exceptions (PausedForInput) instead of
   turning them into an error string.
"""
import pytest

from bouzecode.backend.agent import loop as loop_mod
from bouzecode.backend.agent.loop import resume_paused
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.tools.interaction import PausedForInput


def _ask_tc(tc_id: str, question: str) -> dict:
    return {
        "id": tc_id,
        "name": "AskUserQuestion",
        "input": {"question": question, "allow_freetext": True},
    }


def _drain_until_pause(gen):
    """Consume a resume_paused generator; return the PausedForInput it raises."""
    with pytest.raises(PausedForInput) as exc:
        for _ in gen:
            pass
    return exc.value


def test_resume_paused_chains_multiple_ask(monkeypatch):
    # Force the web-IPC branch of resume_paused (harness patches loop_turn only).
    monkeypatch.setattr(loop_mod, "is_web_ipc_active", lambda: True)

    state = AgentState()
    config: dict = {}

    # Turn had 3 independent AskUserQuestion calls; the 1st (a1) already surfaced &
    # answered. pending_tcs carries all three (a1 will be dropped as already-answered).
    pending = {
        "ask_tc_id": "a1",
        "question": "Q1",
        "pending_tcs": [_ask_tc("a1", "Q1"), _ask_tc("a2", "Q2"), _ask_tc("a3", "Q3")],
    }

    gen1 = resume_paused(pending, "ans1", state, config, "")
    pause2 = _drain_until_pause(gen1)

    # The SECOND question must now be surfaced, not executed.
    assert pause2.ask_tc_id == "a2"
    assert pause2.question == "Q2"
    assert [tc["id"] for tc in pause2.pending_tcs] == ["a2", "a3"]

    # The answer to Q1 landed as a tool_result paired to a1.
    a1_results = [
        m for m in state.messages
        if m.get("role") == "tool" and m.get("tool_call_id") == "a1"
    ]
    assert a1_results and a1_results[0]["content"] == "ans1"
    # No fake error result was fabricated for a2/a3.
    assert not any(
        "Error executing AskUserQuestion" in str(m.get("content", ""))
        for m in state.messages
    )

    # Resume again with the answer to Q2 → the THIRD question is surfaced.
    pending2 = {
        "ask_tc_id": pause2.ask_tc_id,
        "question": pause2.question,
        "pending_tcs": pause2.pending_tcs,
    }
    gen2 = resume_paused(pending2, "ans2", state, config, "")
    pause3 = _drain_until_pause(gen2)

    assert pause3.ask_tc_id == "a3"
    assert pause3.question == "Q3"
    assert [tc["id"] for tc in pause3.pending_tcs] == ["a3"]


def test_execute_tool_propagates_paused():
    from bouzecode.backend.core import tool_registry
    from bouzecode.backend.core.tool_registry import (
        ToolDef,
        execute_tool,
        push_local_overlay,
        pop_local_overlay,
        register_tool,
    )

    def _raiser(params, config):
        raise PausedForInput(question="hello?")

    push_local_overlay()
    try:
        register_tool(ToolDef(
            name="FlowTool",
            schema={"input_schema": {}},
            func=_raiser,
        ))
        # Control-flow exception MUST propagate, not become an error string.
        with pytest.raises(PausedForInput):
            execute_tool("FlowTool", {}, {})
    finally:
        pop_local_overlay()
