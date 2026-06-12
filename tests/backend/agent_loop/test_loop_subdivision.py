# [desc] Tests that agent loop subdivision preserves LoopContext defaults and run() behavior on empty/text-only states. [/desc]
"""Test that loop.run() works correctly after subdivision into sub-modules."""
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.loop_context import LoopContext, TurnAction


def _make_state():
    state = AgentState()
    return state


def _make_config(model="mock"):
    return {"model": model, "auto_permissions": True}


class TestLoopContext:
    def test_default_values(self):
        ctx = LoopContext()
        assert ctx.enforcement_retries == 0
        assert ctx.action == TurnAction.PROCEED
        assert ctx.required_tool is None
        assert ctx.max_nudges == 3

    def test_custom_init(self):
        ctx = LoopContext(required_tool="RunPythonTest", max_nudges=5)
        assert ctx.required_tool == "RunPythonTest"
        assert ctx.max_nudges == 5


class TestRunBasic:
    def test_run_no_message_empty_state(self):
        """run(None) with empty state should return immediately."""
        state = _make_state()
        config = _make_config()
        events = list(run(None, state, config, "system prompt"))
        assert events == []

    def test_run_no_message_text_only_assistant(self):
        """run(None) with last msg being text-only assistant should return None."""
        state = _make_state()
        state.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "tool_calls": []},
        ]
        config = _make_config()
        events = list(run(None, state, config, "system prompt"))
        assert events == []
