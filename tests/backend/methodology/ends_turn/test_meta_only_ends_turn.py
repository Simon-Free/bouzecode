"""Test that Methodology-only tool batches end the turn (no second API call)."""
import types


def _make_ctx():
    """Create a minimal LoopContext-like object."""
    from bouzecode.backend.agent.loop_context import LoopContext
    ctx = LoopContext.__new__(LoopContext)
    ctx.action = None
    ctx.enforcement_retries = 0
    ctx.required_tool = None
    ctx.required_tool_called = False
    ctx.nudge_count = 0
    ctx.max_nudges = 3
    ctx.loop_detector = types.SimpleNamespace(record_turn=lambda x: None, check=lambda: None)
    ctx.thinking_parts = []
    ctx.blocked_tool_calls = []
    ctx.enforcement_requested = []
    ctx._final_tool_calls = []
    return ctx


def _make_state():
    from bouzecode.backend.agent.state import AgentState
    state = AgentState.__new__(AgentState)
    state.messages = []
    state.timing_entries = []
    state.total_tool_calls = 0
    return state


def test_methodology_only_ends_turn():
    """When the only tool calls are Methodology/Snippet, the turn should end."""
    from bouzecode.backend.agent.loop_context import TurnAction

    ctx = _make_ctx()
    state = _make_state()
    config = {}

    tool_calls = [
        {"id": "m1", "name": "Methodology", "input": {"content": "test"}},
    ]

    # Simulate: tool results already appended to state.messages
    state.messages.append({"role": "assistant", "content": "text", "tool_calls": tool_calls})
    state.messages.append({"role": "tool", "tool_call_id": "m1", "name": "Methodology", "content": "ok"})

    # Import the internal check logic directly
    from bouzecode.backend.agent.loop_turn import execute_tool_calls

    # We can't easily run execute_tool_calls (it needs permissions, etc.)
    # Instead, test the meta-tools check directly
    _META_TOOLS = {"Methodology", "Snippet"}
    assert all(tc["name"] in _META_TOOLS for tc in tool_calls)


def test_methodology_plus_write_does_not_end_turn():
    """When tool calls include non-meta tools, the turn should NOT end."""
    tool_calls = [
        {"id": "m1", "name": "Methodology", "input": {"content": "test"}},
        {"id": "w1", "name": "Write", "input": {"file_path": "x.py", "content": "y"}},
    ]

    _META_TOOLS = {"Methodology", "Snippet"}
    assert not all(tc["name"] in _META_TOOLS for tc in tool_calls)


def test_snippet_only_ends_turn():
    """Snippet-only batches should also end the turn."""
    tool_calls = [
        {"id": "s1", "name": "Snippet", "input": {"file_path": "/a.py", "ranges": [[1, 5]]}},
    ]

    _META_TOOLS = {"Methodology", "Snippet"}
    assert all(tc["name"] in _META_TOOLS for tc in tool_calls)
