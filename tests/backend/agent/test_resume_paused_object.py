"""Regression: resume_paused must accept a live PausedForInput OBJECT, not only a dict.

Bug (agents parked on AskUserQuestion never resumed):
  - COLD path (--resume-pending) passes a dict from web_pending.load().
  - WARM path (repl._resume_paused_warm) passes the live PausedForInput OBJECT.
resume_paused indexed it as a dict (pending["ask_tc_id"]) → raised
`TypeError: 'PausedForInput' object is not subscriptable`, crashing every "Reprendre"
of an agent waiting on a question. The fix normalises a non-dict pending to a dict in
the function head. This test drives the WARM path (object) and asserts no crash.
"""
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


def test_resume_paused_accepts_pausedforinput_object(monkeypatch):
    # The single remaining tool_call is the answered AskUserQuestion itself → after it is
    # dropped, to_run is empty → resume_paused falls straight through to run(). Stub run()
    # so no LLM call happens; we only care that the subscript crash is gone.
    monkeypatch.setattr(loop_mod, "run", lambda *a, **k: iter(()))

    state = AgentState()
    config: dict = {}

    # WARM path passes the live OBJECT (this is exactly what repl._resume_paused_warm does).
    pause = PausedForInput(
        question="Q1",
        options=[],
        allow_freetext=True,
        ask_tc_id="a1",
        completed_results={},
        pending_tcs=[_ask_tc("a1", "Q1")],
    )

    # Must NOT raise TypeError: 'PausedForInput' object is not subscriptable.
    list(resume_paused(pause, "ans1", state, config, ""))

    # The answer landed as a tool_result paired to the AskUserQuestion tc_id.
    a1_results = [
        m for m in state.messages
        if m.get("role") == "tool" and m.get("tool_call_id") == "a1"
    ]
    assert a1_results and a1_results[0]["content"] == "ans1"
