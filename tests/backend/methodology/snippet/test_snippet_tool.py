# [desc] Tests for the Snippet tool: appends labeled file ranges into the methodology note.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests for the Snippet tool: appends labeled file ranges into the methodology note.</param></tool_use> [/desc]
"""Tests for context_manager.methodology.snippet_tool."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from bouzecode.backend.context_manager.methodology import snippet_tool
from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE


def _config(state=None) -> dict:
    return {"_context_state": state or ContextState(), "_state": None}


def test_snippet_appends_labeled_block_into_methodology():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "sample.py"
        f.write_text("def a(): pass\ndef b(): pass\ndef c(): pass\n", encoding="utf-8")
        cfg = _config()
        result = snippet_tool(
            {"file_path": str(f), "ranges": [[2, 3]], "label": "b and c"}, cfg,
        )
        note = cfg["_context_state"].notes[METHODOLOGY_NOTE]
        assert "L2-3" in note
        assert "b and c" in note
        assert "def b()" in note and "def c()" in note
        assert "def a()" not in note
        assert "snippet appended: 1 range(s)" in result


def test_snippet_supports_multiple_ranges_in_one_call():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "many.py"
        f.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n", encoding="utf-8")
        cfg = _config()
        snippet_tool(
            {"file_path": str(f), "ranges": [[1, 2], [5, 6], [9, 10]], "label": "tri"}, cfg,
        )
        note = cfg["_context_state"].notes[METHODOLOGY_NOTE]
        assert "line1" in note and "line2" in note
        assert "line5" in note and "line6" in note
        assert "line9" in note and "line10" in note
        assert "line3" not in note and "line7" not in note


def test_snippet_appends_to_existing_methodology():
    gc = ContextState()
    gc.notes[METHODOLOGY_NOTE] = "prior content"
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.py"
        f.write_text("hello\n", encoding="utf-8")
        snippet_tool({"file_path": str(f), "ranges": [[1, 1]], "label": "x"}, {"_context_state": gc})
    note = gc.notes[METHODOLOGY_NOTE]
    assert note.startswith("prior content")
    assert "hello" in note


def test_snippet_relative_path_captures_error_into_note():
    cfg = _config()
    snippet_tool({"file_path": "relative.py", "ranges": [[1, 1]]}, cfg)
    assert "must be absolute" in cfg["_context_state"].notes[METHODOLOGY_NOTE]


def test_snippet_missing_file_captures_error_into_note():
    cfg = _config()
    missing = str(Path(tempfile.gettempdir()).resolve() / "definitely_not_a_real_file_xyz123.py")
    snippet_tool({"file_path": missing, "ranges": [[1, 1]]}, cfg)
    assert "file not found" in cfg["_context_state"].notes[METHODOLOGY_NOTE]


def test_snippet_invalid_range_captures_error():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "f.py"
        f.write_text("a\nb\nc\n", encoding="utf-8")
        cfg = _config()
        snippet_tool({"file_path": str(f), "ranges": [[5, 4]], "label": "rev"}, cfg)
        assert "snippet ERROR" in cfg["_context_state"].notes[METHODOLOGY_NOTE]


def test_snippet_clamps_end_beyond_file_length():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "small.py"
        f.write_text("only\nthree\nlines\n", encoding="utf-8")
        cfg = _config()
        snippet_tool({"file_path": str(f), "ranges": [[1, 999]], "label": "all"}, cfg)
        note = cfg["_context_state"].notes[METHODOLOGY_NOTE]
        assert "only" in note and "three" in note and "lines" in note


def test_snippet_missing_file_path_returns_error_message():
    cfg = _config()
    result = snippet_tool({"ranges": [[1, 1]]}, cfg)
    assert result.startswith("Error:") and "file_path" in result
    assert cfg["_context_state"].notes.get(METHODOLOGY_NOTE, "") == ""


def test_snippet_missing_ranges_returns_error_message():
    cfg = _config()
    result = snippet_tool({"file_path": "/abs/x.py"}, cfg)
    assert result.startswith("Error:") and "ranges" in result
    assert cfg["_context_state"].notes.get(METHODOLOGY_NOTE, "") == ""


def test_snippet_records_timeline_when_state_present():
    class _State:
        turn_count = 3
        notes_timeline: list = []

    state = _State()
    state.notes_timeline = []
    cfg = {"_context_state": ContextState(), "_state": state}
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "t.py"
        f.write_text("hi\n", encoding="utf-8")
        snippet_tool({"file_path": str(f), "ranges": [[1, 1]]}, cfg)
    assert len(state.notes_timeline) == 1
    assert state.notes_timeline[0]["turn"] == 3


def test_snippet_discard_without_ranges_succeeds():
    cfg = _config()
    result = snippet_tool({"file_path": "/some/file.py", "discard": True}, cfg)
    assert "discarded" in result
    assert cfg["_context_state"].notes.get(METHODOLOGY_NOTE, "") == ""


def test_snippet_discard_with_ranges_saves_normally():
    """When ranges is provided, discard is ignored and snippet is saved."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "code.py"
        f.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
        cfg = _config()
        result = snippet_tool(
            {"file_path": str(f), "ranges": [[1, 5]], "discard": True}, cfg
        )
        assert "appended" in result
        assert "line1" in cfg["_context_state"].notes[METHODOLOGY_NOTE]
