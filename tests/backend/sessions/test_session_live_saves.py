# [desc] Tests that session state reflects tool results at ToolEnd/TurnDone events for live-save observers
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that session state reflects tool results at ToolEnd/TurnDone events for live-save observers</param></tool_use> [/desc]
"""Verify that consumers observing ToolEnd / TurnDone can save a session file
that reflects the up-to-date `state.messages` at that moment. Covers the
invariant that powers live-updating the BouzequI Session tab."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bouzecode.backend.agent import AgentState, ToolEnd, TurnDone, run
from bouzecode.backend.agent.loop import resume_paused
from bouzecode.backend.agent.providers.types import AssistantTurn, StreamStarted, TextChunk
from bouzecode.backend.core.tool_registry import ToolDef, clear_registry, register_tool


@pytest.fixture(autouse=True)
def bypass_enforcement(monkeypatch):
    """Disable enforcement hooks so tests don't get extra LLM cycles."""
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])


@pytest.fixture
def echo_tool():
    clear_registry()
    register_tool(ToolDef(
        name="echo",
        schema={
            "name": "echo",
            "description": "echo input",
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
        },
        func=lambda params, _config: f"echoed: {params.get('text', '')}",
        read_only=True,
        concurrent_safe=True,
    ))
    yield
    clear_registry()


def _make_fake_stream(turns):
    iter_turns = iter(turns)

    def fake_stream(**_kwargs):
        turn_spec = next(iter_turns, None)
        if turn_spec is None:
            yield StreamStarted()
            yield AssistantTurn(text="", tool_calls=[], in_tokens=0, out_tokens=0)
            return
        yield StreamStarted()
        if turn_spec.get("text"):
            yield TextChunk(turn_spec["text"])
        yield AssistantTurn(
            text=turn_spec.get("text", ""),
            tool_calls=turn_spec.get("tool_calls", []),
            in_tokens=1,
            out_tokens=1,
        )
    return fake_stream


def _save_session(state, path: Path) -> None:
    path.write_text(
        json.dumps({"messages": list(state.messages)}, default=str),
        encoding="utf-8",
    )


def _drive(events_iter, state, session_path: Path):
    """Consume events and save session at each ToolEnd / TurnDone. Returns snapshots
    of the session file content taken right after each save."""
    snapshots = []
    for event in events_iter:
        if isinstance(event, (ToolEnd, TurnDone)):
            _save_session(state, session_path)
            snapshots.append({
                "event": type(event).__name__,
                "messages": json.loads(session_path.read_text(encoding="utf-8"))["messages"],
            })
    return snapshots


def test_tool_end_observer_sees_tool_in_state_messages(monkeypatch, echo_tool, tmp_path):
    """When the consumer receives ToolEnd for tool X, state.messages[-1] must be X's result."""
    turns = [
        {"tool_calls": [{"id": "c1", "name": "echo", "input": {"text": "hello"}}]},
        {"text": "done"},
    ]
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", _make_fake_stream(turns))

    state = AgentState()
    config = {"model": "test", "permission_mode": "accept-all"}

    observed = []
    for event in run("hi", state, config, "system"):
        if isinstance(event, ToolEnd):
            observed.append({
                "role": state.messages[-1].get("role"),
                "name": state.messages[-1].get("name"),
                "content": state.messages[-1].get("content"),
            })

    assert observed == [{"role": "tool", "name": "echo", "content": "echoed: hello"}]


def test_session_saved_at_tool_end_contains_tool_result(monkeypatch, echo_tool, tmp_path):
    """Consumer that saves on each ToolEnd must end up with a session file
    containing the tool's result message."""
    turns = [
        {"tool_calls": [{"id": "c1", "name": "echo", "input": {"text": "hello"}}]},
        {"text": "done"},
    ]
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", _make_fake_stream(turns))

    state = AgentState()
    config = {"model": "test", "permission_mode": "accept-all"}
    session_path = tmp_path / "session.json"

    snapshots = _drive(run("hi", state, config, "system"), state, session_path)

    tool_end_snapshot = next(s for s in snapshots if s["event"] == "ToolEnd")
    tool_msgs = [m for m in tool_end_snapshot["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["name"] == "echo"
    assert tool_msgs[0]["content"] == "echoed: hello"


def test_session_saved_at_turn_done_contains_assistant_message(monkeypatch, echo_tool, tmp_path):
    """Consumer that saves on TurnDone must capture the assistant message that
    just streamed (no tool calls case)."""
    turns = [{"text": "final answer"}]
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", _make_fake_stream(turns))

    state = AgentState()
    config = {"model": "test", "permission_mode": "accept-all"}
    session_path = tmp_path / "session.json"

    snapshots = _drive(run("hi", state, config, "system"), state, session_path)

    turn_done_snapshot = next(s for s in snapshots if s["event"] == "TurnDone")
    assistant_msgs = [m for m in turn_done_snapshot["messages"] if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "final answer"


def test_parallel_tools_all_in_state_messages_after_last_tool_end(monkeypatch, echo_tool, tmp_path):
    """After 3 parallel tool calls, the last ToolEnd observation must show all 3
    tool results already in state.messages."""
    turns = [
        {"tool_calls": [
            {"id": "c1", "name": "echo", "input": {"text": "a"}},
            {"id": "c2", "name": "echo", "input": {"text": "b"}},
            {"id": "c3", "name": "echo", "input": {"text": "c"}},
        ]},
        {"text": "done"},
    ]
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", _make_fake_stream(turns))

    state = AgentState()
    config = {"model": "test", "permission_mode": "accept-all"}
    session_path = tmp_path / "session.json"

    snapshots = _drive(run("hi", state, config, "system"), state, session_path)

    tool_end_snapshots = [s for s in snapshots if s["event"] == "ToolEnd"]
    assert len(tool_end_snapshots) == 3
    last = tool_end_snapshots[-1]
    tool_msgs = [m for m in last["messages"] if m.get("role") == "tool"]
    assert [m["content"] for m in tool_msgs] == [
        "echoed: a", "echoed: b", "echoed: c",
    ]


def test_resume_paused_tool_end_sees_answer_in_state_messages(monkeypatch, echo_tool, tmp_path):
    """In resume_paused, the first ToolEnd (AskUserQuestion) observation must
    already show the answer in state.messages."""
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", _make_fake_stream([{"text": "done"}]))

    state = AgentState()
    state.messages.append({"role": "user", "content": "q"})
    state.messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "ask1", "name": "AskUserQuestion", "input": {"question": "?"}},
        ],
    })
    config = {"model": "test", "permission_mode": "accept-all"}

    pending = {"ask_tc_id": "ask1", "pending_tcs": []}
    first_tool_end_view = None
    for event in resume_paused(pending, "my-answer", state, config, "system"):
        if isinstance(event, ToolEnd) and first_tool_end_view is None:
            first_tool_end_view = {
                "role": state.messages[-1].get("role"),
                "name": state.messages[-1].get("name"),
                "content": state.messages[-1].get("content"),
            }
            break

    assert first_tool_end_view == {
        "role": "tool", "name": "AskUserQuestion", "content": "my-answer",
    }
