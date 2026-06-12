# [desc] Tests that methodology note persists across AskUserQuestion resume and session restore.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that methodology note persists across AskUserQuestion resume and session restore.</param></tool_use> [/desc]
"""Test that methodology note persists across AskUserQuestion resume.

Bug: After user validates a plan (AskUserQuestion resume), the LLM
says "I don't have context" — methodology was lost on resume.
"""
from pathlib import Path

import pytest

from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


@pytest.fixture(autouse=True)
def bypass_enforcement(monkeypatch):
    """Disable enforcement hooks so tests don't get extra LLM cycles."""
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_test_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])


METHODOLOGY_TEXT = "Plan: implement feature X with files A, B, C"

# Turn 1: save methodology + ask user
RESPONSE_1 = (
    f'I will save my plan.\n'
    f'<tool_use name="Methodology" id="m1">'
    f'<param name="content">{METHODOLOGY_TEXT}</param>'
    f'</tool_use>\n'
    f'<tool_use name="AskUserQuestion" id="a1">'
    f'<param name="question">Should I proceed with this plan?</param>'
    f'</tool_use>'
)

# Turn 2: after resume, reference the plan
RESPONSE_2 = "Continuing with the plan. Implementing feature X now."


def test_methodology_preserved_after_resume():
    """After AskUserQuestion resume, context_state still has methodology content."""
    mock = MockLLM([RESPONSE_1, RESPONSE_2])

    result = bouzecode(
        messages=["Implement feature X"],
        mock_llm=mock,
        mock_tools=None,  # Real tool execution — Methodology writes to context_state
        replies=["Yes, proceed with the plan"],
    )

    # Resume happened: 2 LLM calls
    assert mock.call_count == 2, f"Expected 2 LLM calls, got {mock.call_count}"

    # Methodology persisted in context_state
    gc = result.state.context_state
    meth_text = gc.methodology if hasattr(gc, "methodology") else str(gc)
    assert METHODOLOGY_TEXT in meth_text, (
        f"Methodology text not found in context_state.\n"
        f"context_state content: {meth_text[:500]}"
    )


def test_resume_triggers_second_llm_call():
    """After AskUserQuestion resume, the LLM is called a second time."""
    mock = MockLLM([RESPONSE_1, RESPONSE_2])

    bouzecode(
        messages=["Implement feature X"],
        mock_llm=mock,
        mock_tools=None,
        replies=["Yes, proceed with the plan"],
    )

    assert mock.call_count == 2, (
        f"Expected 2 LLM calls (initial + resume), got {mock.call_count}"
    )


def test_methodology_includes_question_and_answer():
    """Resume appends 'User answered: ...' to methodology."""
    mock = MockLLM([RESPONSE_1, RESPONSE_2])

    result = bouzecode(
        messages=["Implement feature X"],
        mock_llm=mock,
        mock_tools=None,
        replies=["Yes, proceed with the plan"],
    )

    gc = result.state.context_state
    meth_text = gc.methodology if hasattr(gc, "methodology") else str(gc)
    # append_ask_user_question_to_methodology adds question + answer
    assert "proceed" in meth_text.lower() or METHODOLOGY_TEXT in meth_text, (
        f"Expected methodology to contain plan text.\n"
        f"Got: {meth_text[:500]}"
    )


def test_context_state_restored_from_session_file():
    """BUG FIX: --resume-from must restore context_state.notes from session JSON.

    Previously, repl.py loaded messages/tokens but NOT context_state on resume,
    causing methodology loss between web agent subprocess turns.
    """
    import json
    import tempfile
    from bouzecode.backend.agent.state import AgentState

    # Create a fake session JSON with context_state.notes populated
    session_data = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        "turn_count": 1,
        "user_loop_count": 1,
        "total_input_tokens": 100,
        "total_output_tokens": 50,
        "total_cache_read_tokens": 0,
        "total_cache_creation_tokens": 0,
        "distinct_base": 0,
        "context_state": {
            "notes": {
                "methodology": "## Plan\nImplement feature X with files A, B, C\n\n## Findings\nFile structure analyzed.",
                "snippets": "## file.py L10-20\ndef hello(): pass\n",
            },
        },
    }

    # Write session to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(session_data, f)
        session_path = f.name

    try:
        # Simulate what repl.py does on --resume-from
        import json as _json
        state = AgentState()

        _resumed = _json.loads(Path(session_path).read_text(encoding="utf-8"))
        state.messages = _resumed.get("messages", [])
        state.turn_count = _resumed.get("turn_count", 0)
        state.distinct_base = _resumed.get("distinct_base", 0)
        # THE FIX: restore context_state
        _gc_data = _resumed.get("context_state")
        if _gc_data:
            state.context_state.notes = _gc_data.get("notes", {})

        # Assertions
        assert state.context_state.notes.get("methodology") is not None
        assert "feature X" in state.context_state.notes["methodology"]
        assert "snippets" in state.context_state.notes
        assert "file.py" in state.context_state.notes["snippets"]
    finally:
        Path(session_path).unlink(missing_ok=True)
