# [desc] Tests that context-only tools (Methodology/Snippet) end the loop while real tools continue it. [/desc]
"""Verify that when the LLM emits only Methodology/Snippet, the loop breaks immediately."""
import pytest
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


METH = '<tool_use name="Methodology" id="m1"><param name="content">done</param></tool_use>'
SNIP = '<tool_use name="Snippet" id="s1"><param name="file_path">/x.py</param><param name="discard">true</param></tool_use>'
BASH = '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'


def test_methodology_only_is_final_answer():
    """Single Methodology tool → loop breaks, no 2nd LLM call."""
    mock = MockLLM([f"All done.\n{METH}"])
    result = bouzecode(["Hi"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 1


def test_methodology_and_snippet_is_final_answer():
    """Methodology + Snippet → loop breaks, no 2nd LLM call."""
    mock = MockLLM([f"Noted.\n{METH}\n{SNIP}"])
    result = bouzecode(["Hi"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 1


def test_methodology_plus_real_tool_continues():
    """Methodology + Bash → loop continues (Bash is not context-only)."""
    mock = MockLLM([
        f"{METH}\n{BASH}",
        f"Command done.\n{METH}",
    ])
    result = bouzecode(["Run something"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 2
    assert "Command done." in result.last_reply
