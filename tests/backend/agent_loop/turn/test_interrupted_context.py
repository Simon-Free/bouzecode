# [desc] Tests that Ctrl+C interrupted context is preserved as ephemeral tokens and cleaned up on next run. [/desc]
"""E2E test: Ctrl+C interrupted context is preserved as ephemeral fresh tokens."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.minimal_payload import build_minimal_payload
from tests.fake_llm import MockLLM


def _make_state():
    state = AgentState()
    state.context_state = MagicMock()
    state.context_state.methodology_content = ""
    return state


def test_interrupted_turn_creates_interrupted_message(monkeypatch):
    """When cancel_check fires during streaming, an _interrupted msg is added."""
    mock = MockLLM(["This is a long response that will be interrupted mid-stream"])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", mock.stream)

    # cancel_check fires on 3rd call: #1=loop top, #2=after StreamStarted yield,
    # #3=after TextChunk yield (text_parts already populated at this point)
    call_count = {"n": 0}

    def cancel_check():
        call_count["n"] += 1
        return call_count["n"] >= 3

    state = _make_state()
    config = {"model": "mock", "thinking_overflow_limit": 0}

    events = list(run("Hello", state, config, "system", cancel_check=cancel_check))

    interrupted_msgs = [m for m in state.messages if m.get("_interrupted")]
    assert len(interrupted_msgs) == 1
    assert "This is a long" in interrupted_msgs[0]["content"]


def test_interrupted_content_injected_in_next_payload():
    """build_minimal_payload injects _interrupted content as prefix of user msg."""
    messages = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "I was saying...", "tool_calls": [], "_interrupted": True},
        {"role": "user", "content": "Actually, change direction"},
    ]

    payload = build_minimal_payload(messages)

    assert len(payload) == 1
    assert payload[0]["role"] == "user"
    assert "user interrupted" in payload[0]["content"].lower()
    assert "I was saying..." in payload[0]["content"]
    assert "Actually, change direction" in payload[0]["content"]


def test_interrupted_content_not_in_payload_after_next_turn():
    """After the next full LLM response, _interrupted content disappears."""
    messages = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "Partial...", "tool_calls": [], "_interrupted": True},
        {"role": "user", "content": "New direction"},
        {"role": "assistant", "content": "OK", "tool_calls": [{"id": "t1", "name": "Bash", "input": {"command": "echo hi"}}]},
        {"role": "tool", "tool_use_id": "t1", "content": "hi"},
        {"role": "user", "content": "Thanks"},
    ]

    payload = build_minimal_payload(messages)

    full_text = " ".join(m.get("content", "") for m in payload)
    assert "Partial..." not in full_text


def test_cleanup_removes_old_interrupted_on_new_run(monkeypatch):
    """run() cleans up _interrupted messages at the start."""
    state = _make_state()
    state.messages = [
        {"role": "user", "content": "Old question"},
        {"role": "assistant", "content": "Old partial", "tool_calls": [], "_interrupted": True},
    ]

    # Use a Methodology tool call to satisfy enforcement (avoids infinite loop)
    mock = MockLLM([
        'done.\n<tool_use name="Methodology" id="m1"><param name="content">noted</param></tool_use>'
    ])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", mock.stream)

    config = {"model": "mock", "thinking_overflow_limit": 0}

    events = list(run("New question", state, config, "system", cancel_check=None))

    interrupted_msgs = [m for m in state.messages if m.get("_interrupted")]
    assert len(interrupted_msgs) == 0
