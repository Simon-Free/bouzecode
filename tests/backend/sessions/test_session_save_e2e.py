# [desc] E2E tests verifying session save preserves thinking blocks, strips tool_use XML, and captures notes
# <tool_use name="FinalAnswer" id="f1"><param name="answer">E2E tests verifying session save preserves thinking blocks, strips tool_use XML, and captures notes</param></tool_use> [/desc]
"""Session save behaviour grounded in real bouzecode() conversations.

Replaces the hand-built-state / MagicMock unit tests that called
_build_session_data / _clean_message / cmd_clear on fabricated AgentState:
- test_session_build_data.py
- test_session_thinking_preserved.py
- test_session_thinking_bug.py
- test_thinking_session_bug.py
- test_cmd_clear_context_state.py

Here we run a REAL conversation (the mocked model streams thinking + emits
tool_use + visible text + a Methodology note), then call the REAL
_build_session_data(result.state) and assert on the JSON-able dict the renderer
would persist. The /save and /clear paths are slash commands not emittable by
the loop, so we exercise the real underlying functions on result.state after a
real conversation (the methodology mandates this for slash-command behaviour).

MockLLM dict responses ({"thinking": [...], "text": ...}) emit real
ThinkingChunk events, so the loop's _build_assistant_content prepends a real
<thinking> block into state.messages — exactly what a thinking turn produces.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE
from bouzecode.backend.commands.session import _build_session_data
from bouzecode.backend.commands.core.basic import cmd_clear

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
READ_TOOL = '<tool_use name="Read" id="r1"><param name="file_path">/abs/foo.py</param></tool_use>'
# Read returns snippetable output → the next turn must Snippet(discard) it to
# satisfy enforcement before the conversation can end.
DISCARD = ('<tool_use name="Snippet" id="s1"><param name="file_path">/abs/foo.py</param>'
           '<param name="discard">true</param></tool_use>')


def _assistant_msgs(data):
    return [m for m in data["messages"] if m.get("role") == "assistant"]


# ── thinking + text turn → saved JSON keeps thinking, strips tool_use ─────────

def test_save_preserves_thinking_and_strips_tool_use():
    """A turn that streams thinking, then emits visible text + a tool_use:
    the saved assistant content keeps <thinking> but drops the tool_use XML."""
    mock = MockLLM([
        {"thinking": ["Let me analyze this problem step by step."],
         "text": f"I found the issue in the parser.\n{METH}\n{READ_TOOL}"},
        f"{METH}\n{DISCARD}",
        {"text": f"done.\n{METH}"},
    ])
    result = bouzecode(["fix the parser bug"], mock_llm=mock, mock_tools=True)

    data = _build_session_data(result.state, session_id="t1")
    saved = next(m["content"] for m in _assistant_msgs(data)
                 if "<thinking>" in m.get("content", ""))
    assert "<thinking>" in saved
    assert "analyze this problem" in saved
    assert "I found the issue" in saved
    assert "<tool_use" not in saved          # tool XML stripped (renderer uses tool_calls)
    assert 'name="Read"' not in saved


# ── thinking-only turn → not reduced to "." ──────────────────────────────────

def test_save_thinking_only_message_not_dot():
    """A turn whose only visible output is thinking must survive as the thinking,
    never collapse to '.' (the renderer would otherwise show a bare dot)."""
    mock = MockLLM([
        {"thinking": ["Planning my approach to this task."],
         "text": f"{METH}"},
        f"done.\n{METH}",   # the silent meta-only turn above gets a continue-nudge
    ])
    result = bouzecode(["help me"], mock_llm=mock)

    data = _build_session_data(result.state, session_id="t2")
    thinking_msgs = [m for m in _assistant_msgs(data)
                     if "<thinking>" in m.get("content", "")]
    assert thinking_msgs, "no thinking-only assistant message was saved"
    for m in thinking_msgs:
        assert m["content"] != "."
        assert "Planning my approach" in m["content"]


# ── context_state notes captured from the real methodology note ───────────────────

def test_save_includes_context_state_notes_from_conversation():
    """The methodology note the conversation built lands in context_state.notes."""
    meth = '<tool_use name="Methodology" id="m1"><param name="content">key finding here</param></tool_use>'
    result = bouzecode(["investigate X"], mock_llm=MockLLM([f"done.\n{meth}"]))

    # sanity: the live note exists on the state
    assert "key finding here" in result.state.context_state.notes.get(METHODOLOGY_NOTE, "")

    data = _build_session_data(result.state, session_id="t3")
    assert "gc_state" in data and "notes" in data["gc_state"]
    assert "key finding here" in data["gc_state"]["notes"].get(METHODOLOGY_NOTE, "")


def test_save_no_attribute_error_on_real_state():
    """_build_session_data reads state.context_state.notes without AttributeError
    even on a minimal one-turn conversation."""
    result = bouzecode(["hello"], mock_llm=MockLLM([f"done.\n{METH}"]))
    data = _build_session_data(result.state)
    assert "gc_state" in data
    assert isinstance(data["gc_state"]["notes"], dict)


# ── tool-only turn (no thinking, no text) → "." fallback ─────────────────────

def test_save_tool_only_turn_collapses_to_dot():
    """A turn that is pure tool_use (no visible text, no thinking) is saved as
    the '.' fallback — the renderer relies on tool_calls for the actual call."""
    mock = MockLLM([
        f"{METH}\n{READ_TOOL}",
        f"{METH}\n{DISCARD}",
        f"done.\n{METH}",
    ])
    result = bouzecode(["read it"], mock_llm=mock, mock_tools=True)

    data = _build_session_data(result.state, session_id="t4")
    tool_only = [m for m in _assistant_msgs(data) if m["content"] == "."]
    assert tool_only, "expected a tool-only assistant message collapsed to '.'"
    for m in _assistant_msgs(data):
        assert "<tool_use" not in m["content"]


# ── /clear on a real conversation state clears the notes ─────────────────────

def test_cmd_clear_wipes_notes_built_by_conversation(tmp_path):
    """After a conversation populates context_state.notes, the real cmd_clear
    must reset them to {} without crashing (regression: AttributeError on
    context_state)."""
    meth = '<tool_use name="Methodology" id="m1"><param name="content">notes to wipe</param></tool_use>'
    result = bouzecode(["do work"], mock_llm=MockLLM([f"done.\n{meth}"]))
    state = result.state
    assert state.context_state.notes.get(METHODOLOGY_NOTE)  # populated by the run

    config = {"model": "test", "_session_path": str(tmp_path / "s.json")}
    cmd_clear("", state, config)

    assert state.context_state.notes == {}
    assert state.messages == []
