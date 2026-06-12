"""Tests for close_reason telemetry field.

Verifies that AgentState.close_reason is correctly set for:
- "no_tools_text": assistant replies with text but no tool calls
- "compliance_close": meta-only batch after compliance turn
- "final_answer": FinalAnswer tool ends the session
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.providers.types import (
    AssistantTurn,
    StreamStarted,
    TextChunk,
)
from bouzecode.backend.core.tool_registry import ToolDef, clear_registry, register_tool


def _make_fake_stream(turns):
    """Create a fake stream function that yields pre-defined turns."""
    iter_turns = iter(turns)

    def fake_stream(**_kwargs):
        turn_spec = next(iter_turns, None)
        if turn_spec is None:
            yield StreamStarted()
            yield AssistantTurn(text="", tool_calls=[], in_tokens=0, out_tokens=0)
            return
        yield StreamStarted()
        text = turn_spec.get("text", "")
        if text:
            yield TextChunk(text)
        yield AssistantTurn(
            text=text,
            tool_calls=turn_spec.get("tool_calls", []),
            in_tokens=1,
            out_tokens=1,
        )

    return fake_stream


@pytest.fixture
def bypass_enforcement(monkeypatch):
    """Disable enforcement hooks so tests don't get extra LLM cycles."""
    monkeypatch.setattr(
        "bouzecode.backend.tools.enforcement_hooks.check_enforcement",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads",
        lambda *a, **kw: [],
    )


@pytest.fixture
def final_answer_tool():
    """Register a FinalAnswer tool that ends the turn."""
    clear_registry()
    register_tool(ToolDef(
        name="FinalAnswer",
        schema={
            "name": "FinalAnswer",
            "description": "End session",
            "input_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        },
        func=lambda params, _config: params.get("answer", ""),
        ends_turn=True,
    ))
    yield
    clear_registry()


@pytest.fixture
def methodology_tool():
    """Register a Methodology tool (meta-only)."""
    clear_registry()
    register_tool(ToolDef(
        name="Methodology",
        schema={
            "name": "Methodology",
            "description": "Save methodology note",
            "input_schema": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
            },
        },
        func=lambda params, _config: "saved",
        read_only=True,
        concurrent_safe=True,
    ))
    yield
    clear_registry()


def _base_config():
    return {
        "model": "test-model",
        "enforce_methodology": False,
        "task_classification": False,
        "paralysis_abort_after": 0,
    }


def test_close_reason_no_tools_text(monkeypatch, bypass_enforcement):
    """Assistant replies with only text (no tool calls) → close_reason='no_tools_text'."""
    fake = _make_fake_stream([{"text": "All done, nothing to do."}])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake)

    state = AgentState()
    config = _base_config()
    list(run("hello", state, config, "system prompt"))

    assert state.close_reason == "no_tools_text"


def test_close_reason_final_answer(monkeypatch, bypass_enforcement, final_answer_tool):
    """FinalAnswer tool ends the session → close_reason='final_answer'."""
    fake = _make_fake_stream([{
        "text": "Here is your answer.",
        "tool_calls": [{
            "name": "FinalAnswer",
            "id": "fa1",
            "input": {"answer": "done"},
        }],
    }])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake)

    state = AgentState()
    config = _base_config()
    list(run("do something", state, config, "system prompt"))

    assert state.close_reason == "final_answer"


def test_close_reason_no_tools_text_after_work(monkeypatch, methodology_tool):
    """Fallback B supprimé (82fe4b87) : un tour texte sans tool calls clôt la
    session immédiatement avec close_reason='no_tools_text' — plus de tour de
    conformité ni de 'compliance_close'."""
    # Turn 1: productive Bash call
    # Turn 2: text but no tool calls → BREAK direct (no_tools_text)
    fake = _make_fake_stream([
        {"text": "", "tool_calls": [{
            "name": "Bash",
            "id": "b1",
            "input": {"command": "echo ok"},
        }]},
        {"text": "Let me think about this.", "tool_calls": []},
    ])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake)
    monkeypatch.setattr(
        "bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads",
        lambda *a, **kw: [],
    )

    state = AgentState()
    config = _base_config()
    config["enforce_methodology"] = True
    list(run("hello", state, config, "system prompt"))

    assert state.close_reason == "no_tools_text"
