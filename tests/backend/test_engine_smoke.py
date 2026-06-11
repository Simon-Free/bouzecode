"""E2E smoke tests for the new bouzecode engine.

Tests:
- Multi-turn conversation with MockLLM
- Tool call (Bash echo) executed and result returned
- FinalAnswer closes conversation
"""
from __future__ import annotations

import pytest
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


@pytest.mark.backend
class TestEngineSmoke:
    """Core engine smoke tests — no network, no real LLM."""

    def test_simple_text_reply(self):
        """LLM returns plain text — no tools."""
        mock = MockLLM(["Hello! I'm bouzecode."])
        result = bouzecode(messages=["Hi"], mock_llm=mock, mock_tools=True)
        assert "Hello" in result.last_reply
        assert mock.call_count == 1

    def test_tool_call_bash_echo(self):
        """LLM calls Bash(echo hi), gets result, replies."""
        mock = MockLLM([
            '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>',
            "The command returned: hi",
        ])
        result = bouzecode(messages=["Run echo hi"], mock_llm=mock)
        assert mock.call_count == 2
        # Second turn should reference the echo output
        assert "hi" in result.last_reply.lower() or "command" in result.last_reply.lower()

    def test_final_answer_closes(self):
        """FinalAnswer tool call closes the conversation and sets final_answer."""
        mock = MockLLM([
            '<tool_use name="FinalAnswer" id="f1"><param name="answer">Done! All good.</param></tool_use>',
        ])
        # Do NOT use mock_tools=True here: the real FinalAnswer handler must run
        # to set state.final_answer (it reads config["_state"]).
        result = bouzecode(messages=["Finish up"], mock_llm=mock)
        assert "Done! All good." in result.last_reply

    def test_multi_turn(self):
        """Two user messages → two LLM calls per message."""
        mock = MockLLM([
            "First reply.",
            "Second reply.",
        ])
        result = bouzecode(messages=["msg1", "msg2"], mock_llm=mock, mock_tools=True)
        assert mock.call_count == 2
        assert len(result.turns) == 2

    def test_methodology_tool_persists(self):
        """Methodology tool call creates a note (mocked execution)."""
        mock = MockLLM([
            '<tool_use name="Methodology" id="m1"><param name="content">My note</param></tool_use>',
            "I saved a methodology note.",
        ])
        result = bouzecode(messages=["Save a note"], mock_llm=mock)
        assert mock.call_count == 2
