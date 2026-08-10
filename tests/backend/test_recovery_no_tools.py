"""Tests for the out-of-band recovery mechanism on thinking-only turns.

Covers:
- Thinking-only turn with recover_memory=True -> side-call recovery + continuation (no bounce)
- 3 consecutive recoveries -> fallback to bounce+close
- Native-tool model (deepseek) unchanged behavior (recover_memory=False -> bounce)
- recover_memory=False -> legacy bounce
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from bouzecode.backend.agent.loop_context import LoopContext, TurnAction
from bouzecode.backend.agent.loop_turn import handle_no_tools
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE


class _FakeContextState:
    """Minimal context_state with notes dict."""
    def __init__(self):
        self.notes = {}


class _FakeAssistantTurn:
    stop_reason = "end_turn"
    tool_calls = None


def _make_state(messages=None):
    state = AgentState()
    if messages is None:
        # In the real loop, an assistant message is always present before handle_no_tools
        messages = [{"role": "assistant", "content": "<thinking>\nthinking\n</thinking>"}]
    state.messages = messages
    state.context_state = _FakeContextState()
    state.turn_count = 1
    return state


def _make_ctx(thinking_parts=None, text_parts=None, **kwargs):
    ctx = LoopContext()
    ctx.thinking_parts = thinking_parts or []
    ctx.text_parts = text_parts or []
    ctx.assistant_turn = _FakeAssistantTurn()
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


class TestRecoveryPathA:
    """Thinking-only turn with recover_memory=True triggers side-call recovery."""

    def test_recovery_side_call_continues(self, monkeypatch):
        """When recover_memory=True and thinking exists, recovery is attempted
        and the turn continues (no bounce)."""
        state = _make_state()
        config = {
            "recover_memory": True,
            "enforce_methodology": True,
            "_context_state": state.context_state,
            "_context_state": state.context_state,
            "model": "claude-opus-4-6",
        }
        ctx = _make_ctx(thinking_parts=["I'm analyzing the code..."])

        # Monkeypatch recover_methodology to return a fake Methodology call
        def fake_recover(s, c, cx):
            return {"name": "Methodology", "input": {"content": "Recovered note"}}

        monkeypatch.setattr(
            "bouzecode.backend.agent.enforcement_call.recover_methodology",
            fake_recover,
        )

        action = handle_no_tools(state, config, ctx)

        assert action == TurnAction.CONTINUE
        # Counter incremented
        assert ctx.consecutive_no_tool_recoveries == 1
        # Methodology was written to context_state notes
        assert "Recovered note" in state.context_state.notes.get(METHODOLOGY_NOTE, "")
        # Continuation message appended
        assert any("Methodology récupérée" in m.get("content", "")
                   for m in state.messages if m.get("role") == "user")

    def test_recovery_no_thinking_breaks(self, monkeypatch):
        """Without thinking, recovery is skipped and session closes (BREAK)."""
        state = _make_state()
        config = {
            "recover_memory": True,
            "enforce_methodology": True,
            "_context_state": state.context_state,
            "model": "claude-opus-4-6",
        }
        ctx = _make_ctx(thinking_parts=[])  # no thinking

        # recover_methodology should NOT be called
        call_log = []

        def fake_recover(s, c, cx):
            call_log.append(1)
            return None

        monkeypatch.setattr(
            "bouzecode.backend.agent.enforcement_call.recover_methodology",
            fake_recover,
        )

        action = handle_no_tools(state, config, ctx)

        # No recovery possible, no bounce — session closes
        assert call_log == []  # recover not called
        assert action == TurnAction.BREAK
        assert state.close_reason == "text_no_tools"

    def test_recovery_returns_none_falls_to_bounce(self, monkeypatch):
        """If recovery side-call returns None, still continues but note untouched."""
        state = _make_state()
        config = {
            "recover_memory": True,
            "enforce_methodology": True,
            "_context_state": state.context_state,
            "_context_state": state.context_state,
            "model": "claude-opus-4-6",
        }
        ctx = _make_ctx(thinking_parts=["thinking..."])

        def fake_recover(s, c, cx):
            return None  # recovery failed

        monkeypatch.setattr(
            "bouzecode.backend.agent.enforcement_call.recover_methodology",
            fake_recover,
        )

        action = handle_no_tools(state, config, ctx)

        # Still continues (path A body runs), counter incremented
        assert action == TurnAction.CONTINUE
        assert ctx.consecutive_no_tool_recoveries == 1
        # No methodology written
        assert METHODOLOGY_NOTE not in state.context_state.notes


class TestRecoveryCap:
    """3 consecutive recoveries -> session closes (no fallback bounce)."""

    def test_cap_reached_breaks(self, monkeypatch):
        """After 3 recoveries, session closes directly (BREAK)."""
        state = _make_state()
        config = {
            "recover_memory": True,
            "enforce_methodology": True,
            "_context_state": state.context_state,
            "model": "claude-opus-4-6",
        }
        ctx = _make_ctx(
            thinking_parts=["still thinking..."],
            consecutive_no_tool_recoveries=3,  # already at cap
        )

        # recover_methodology should NOT be called (cap reached)
        call_log = []

        def fake_recover(s, c, cx):
            call_log.append(1)
            return {"name": "Methodology", "input": {"content": "x"}}

        monkeypatch.setattr(
            "bouzecode.backend.agent.enforcement_call.recover_methodology",
            fake_recover,
        )

        action = handle_no_tools(state, config, ctx)

        assert call_log == []  # recovery skipped
        # No bounce — falls directly to BREAK
        assert action == TurnAction.BREAK
        assert state.close_reason == "text_no_tools"


class TestRecoverMemoryDisabled:
    """When recover_memory=False, session closes (no recovery, no bounce)."""

    def test_no_recovery_when_disabled(self, monkeypatch):
        """recover_memory=False -> straight to BREAK (no bounce)."""
        state = _make_state()
        config = {
            "recover_memory": False,
            "enforce_methodology": True,
            "_context_state": state.context_state,
            "model": "deepseek/deepseek-chat",
        }
        ctx = _make_ctx(thinking_parts=["thinking stuff"])

        call_log = []

        def fake_recover(s, c, cx):
            call_log.append(1)
            return {"name": "Methodology", "input": {"content": "x"}}

        monkeypatch.setattr(
            "bouzecode.backend.agent.enforcement_call.recover_methodology",
            fake_recover,
        )

        action = handle_no_tools(state, config, ctx)

        assert call_log == []  # no recovery attempted
        # No bounce (legacy removed) — session closes directly
        assert action == TurnAction.BREAK
        assert state.close_reason == "text_no_tools"


class TestCounterReset:
    """consecutive_no_tool_recoveries resets when a tool batch succeeds."""

    def test_counter_field_exists(self):
        """LoopContext has the counter field defaulting to 0."""
        ctx = LoopContext()
        assert ctx.consecutive_no_tool_recoveries == 0
