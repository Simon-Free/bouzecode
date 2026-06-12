# [desc] Tests for methodology note append/replace logic and auto-append hooks (user messages, plans, Q&A). [/desc]
"""Tests for context_manager.methodology — append/replace + auto-append hooks."""
from __future__ import annotations

from bouzecode.backend.context_manager.methodology import (
    append_ask_user_question_to_methodology,
    append_plan_to_methodology,
    append_user_msg_to_methodology,
    methodology_tool,
)
from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE


def _config(state=None) -> dict:
    return {"_context_state": state or ContextState(), "_state": None}


def test_append_to_empty_methodology():
    cfg = _config()
    res = methodology_tool({"content": "first finding"}, cfg)
    assert "now 13 chars" in res
    assert cfg["_context_state"].notes[METHODOLOGY_NOTE] == "first finding"


def test_append_extends_existing():
    gc = ContextState()
    gc.notes[METHODOLOGY_NOTE] = "## Goal\nfix the bug"
    res = methodology_tool({"content": "## Findings\nbug is in foo()"}, {"_context_state": gc, "_state": None})
    assert "## Goal" in gc.notes[METHODOLOGY_NOTE]
    assert "## Findings" in gc.notes[METHODOLOGY_NOTE]
    assert "1 chars" not in res  # sanity: new size is reported


def test_mode_replace_treated_as_append():
    """mode='replace' was removed — now just appends like default."""
    gc = ContextState()
    gc.notes[METHODOLOGY_NOTE] = "existing content"
    methodology_tool(
        {"mode": "replace", "content": "new content"},
        {"_context_state": gc, "_state": None},
    )
    new = gc.notes[METHODOLOGY_NOTE]
    assert "existing content" in new
    assert "new content" in new


def test_append_user_msg_to_methodology_adds_block():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "fix the lease bug please")
    note = gc.notes[METHODOLOGY_NOTE]
    assert note.startswith("## User @")
    assert "fix the lease bug please" in note


def test_append_user_msg_keeps_history():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "first instruction")
    append_user_msg_to_methodology(gc, "second instruction")
    note = gc.notes[METHODOLOGY_NOTE]
    assert "first instruction" in note
    assert "second instruction" in note
    assert note.count("## User @") == 2


def test_append_user_msg_then_replace_preserves_users():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "initial ask")
    methodology_tool({"content": "## Plan\nimplement X"}, {"_context_state": gc, "_state": None})
    methodology_tool({"content": "## NewPlan"}, {"_context_state": gc, "_state": None})
    note = gc.notes[METHODOLOGY_NOTE]
    assert "initial ask" in note
    assert "## NewPlan" in note
    assert "implement X" in note  # append mode keeps everything


def test_append_plan_adds_block():
    gc = ContextState()
    append_plan_to_methodology(gc, "1. read file\n2. edit\n3. run tests")
    note = gc.notes[METHODOLOGY_NOTE]
    assert note.startswith("## Plan @")
    assert "1. read file" in note
    assert "3. run tests" in note


def test_append_plan_ignores_empty_content():
    gc = ContextState()
    append_plan_to_methodology(gc, "")
    append_plan_to_methodology(gc, "   \n   ")
    assert gc.notes.get(METHODOLOGY_NOTE, "") == ""


def test_append_ask_user_question_adds_block():
    gc = ContextState()
    append_ask_user_question_to_methodology(gc, "which DB should I use?", "postgres")
    note = gc.notes[METHODOLOGY_NOTE]
    assert note.startswith("## Q&A @")
    assert "**Q:** which DB should I use?" in note
    assert "**A:** postgres" in note


def test_append_ask_user_question_handles_missing_answer():
    gc = ContextState()
    append_ask_user_question_to_methodology(gc, "proceed?", "")
    note = gc.notes[METHODOLOGY_NOTE]
    assert "**Q:** proceed?" in note
    assert "**A:** \n" in note or note.rstrip().endswith("**A:**")


def test_interleaved_order_preserved():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "first user ask")
    append_plan_to_methodology(gc, "plan one")
    append_ask_user_question_to_methodology(gc, "Q1?", "A1")
    append_user_msg_to_methodology(gc, "second user ask")
    append_plan_to_methodology(gc, "plan two")
    note = gc.notes[METHODOLOGY_NOTE]
    positions = [
        note.find("first user ask"),
        note.find("plan one"),
        note.find("Q1?"),
        note.find("second user ask"),
        note.find("plan two"),
    ]
    assert all(p != -1 for p in positions)
    assert positions == sorted(positions)


def test_append_preserves_all_blocks():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "keep me")
    append_plan_to_methodology(gc, "transient plan")
    append_ask_user_question_to_methodology(gc, "Q?", "A")
    methodology_tool({"content": "fresh"}, {"_context_state": gc, "_state": None})
    note = gc.notes[METHODOLOGY_NOTE]
    assert "keep me" in note
    assert "fresh" in note
    assert "transient plan" in note  # append mode keeps everything
    assert "Q?" in note
