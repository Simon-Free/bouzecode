"""Tests for stale snippet marking.

Covers:
- _mark_stale_snippets: appends stale markers for range-based snippets
- No false positive: edits to unrelated files don't mark anything
- Symbol snippets are NOT marked stale (they auto-refresh)
- End-to-end: Edit tool triggers stale marking via hook
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE
from bouzecode.backend.context_manager.stale_hooks import _mark_stale_snippets


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _register_tools():
    """Ensure all tools (Edit, Write, etc.) and hooks are registered."""
    import bouzecode.backend.tools.registration  # noqa: F401


@pytest.fixture
def context_state():
    """Fresh ContextState with empty methodology note."""
    state = ContextState()
    state.notes[METHODOLOGY_NOTE] = ""
    return state


@pytest.fixture
def tmp_py_file(tmp_path):
    """Create a temporary Python file for Edit tests."""
    f = tmp_path / "example.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    return f


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: _mark_stale_snippets
# ──────────────────────────────────────────────────────────────────────────────

class TestMarkStaleSnippets:
    def test_marks_range_snippet_for_edited_file(self, context_state):
        """Range snippet matching edited file gets a stale marker."""
        path = r"C:\project\src\foo.py"
        context_state.notes[METHODOLOGY_NOTE] = (
            "## snippet: C:\\project\\src\\foo.py L10-25 — \"some label\"\n"
            "   10\tdef foo():\n"
            "   11\t    pass\n"
        )

        _mark_stale_snippets(context_state, path)

        note = context_state.notes[METHODOLOGY_NOTE]
        assert "## snippet-stale: C:\\project\\src\\foo.py L10-25" in note
        assert "STALE" in note

    def test_marks_multiple_range_snippets(self, context_state):
        """Multiple range snippets for same file all get marked."""
        path = r"C:\project\src\foo.py"
        context_state.notes[METHODOLOGY_NOTE] = (
            "## snippet: C:\\project\\src\\foo.py L10-25 — \"first\"\n"
            "   10\tdef foo():\n\n"
            "## snippet: C:\\project\\src\\foo.py L40-50 — \"second\"\n"
            "   40\tdef bar():\n"
        )

        _mark_stale_snippets(context_state, path)

        note = context_state.notes[METHODOLOGY_NOTE]
        assert "## snippet-stale: C:\\project\\src\\foo.py L10-25" in note
        assert "## snippet-stale: C:\\project\\src\\foo.py L40-50" in note

    def test_no_mark_for_unrelated_file(self, context_state):
        """Editing a different file doesn't mark any snippet stale."""
        context_state.notes[METHODOLOGY_NOTE] = (
            "## snippet: C:\\project\\src\\foo.py L10-25 — \"foo stuff\"\n"
            "   10\tdef foo():\n"
        )

        _mark_stale_snippets(context_state, r"C:\project\src\bar.py")

        note = context_state.notes[METHODOLOGY_NOTE]
        assert "snippet-stale" not in note

    def test_symbol_snippet_marked_stale(self, context_state):
        """Symbol-based snippets ARE marked stale (append-only) when edited.

        They are never re-resolved in place — that mutated the cached block and
        broke the prompt-cache prefix. The stale marker references the symbol."""
        path = r"C:\project\src\foo.py"
        context_state.notes[METHODOLOGY_NOTE] = (
            "## snippet: C:\\project\\src\\foo.py :: my_func — \"symbol snippet\"\n"
            "   10\tdef my_func():\n"
            "   11\t    pass\n"
        )

        _mark_stale_snippets(context_state, path)

        note = context_state.notes[METHODOLOGY_NOTE]
        assert "## snippet-stale: C:\\project\\src\\foo.py :: my_func" in note
        # The original cached snippet body must remain untouched (append-only).
        assert "def my_func():" in note

    def test_no_double_marking(self, context_state):
        """Already-stale snippet is not marked again."""
        path = r"C:\project\src\foo.py"
        context_state.notes[METHODOLOGY_NOTE] = (
            "## snippet: C:\\project\\src\\foo.py L10-25 — \"foo\"\n"
            "   10\tdef foo():\n\n"
            "## snippet-stale: C:\\project\\src\\foo.py L10-25 — STALE (file edited; re-read or re-snippet with symbol=)"
        )

        _mark_stale_snippets(context_state, path)

        note = context_state.notes[METHODOLOGY_NOTE]
        # Count occurrences — should be exactly 1
        assert note.count("## snippet-stale: C:\\project\\src\\foo.py L10-25") == 1

    def test_empty_methodology_note(self, context_state):
        """Empty note → no crash, no markers."""
        context_state.notes[METHODOLOGY_NOTE] = ""
        _mark_stale_snippets(context_state, r"C:\project\src\foo.py")
        assert context_state.notes[METHODOLOGY_NOTE] == ""

    def test_case_insensitive_path_matching(self, context_state):
        """Path matching is case-insensitive (Windows)."""
        context_state.notes[METHODOLOGY_NOTE] = (
            "## snippet: C:\\Project\\Src\\Foo.py L10-25 — \"mixed case\"\n"
            "   10\tdef foo():\n"
        )

        _mark_stale_snippets(context_state, r"c:\project\src\foo.py")

        note = context_state.notes[METHODOLOGY_NOTE]
        assert "snippet-stale" in note

    def test_forward_slash_path_matching(self, context_state):
        """Forward slashes in edited path match backslashes in snippet."""
        context_state.notes[METHODOLOGY_NOTE] = (
            "## snippet: C:\\project\\src\\foo.py L5-15 — \"backslash\"\n"
            "   5\tpass\n"
        )

        _mark_stale_snippets(context_state, "C:/project/src/foo.py")

        note = context_state.notes[METHODOLOGY_NOTE]
        assert "snippet-stale" in note


# ──────────────────────────────────────────────────────────────────────────────
# Integration test: Edit tool triggers stale marking via hook
# ──────────────────────────────────────────────────────────────────────────────

class TestEditHookIntegration:
    @pytest.fixture(autouse=True)
    def _register_tools(self):
        """Re-register tools + stale hooks (conftest snapshots empty registry)."""
        from bouzecode.backend.tools.registration import _register_builtins
        from bouzecode.backend.context_manager import stale_hooks

        _register_builtins()
        # Reset hook flag so hooks get re-installed on fresh tool funcs
        stale_hooks._hooks_installed = False
        stale_hooks.install_stale_hooks()

    def test_edit_marks_snippet_stale(self, context_state, tmp_py_file):
        """Calling Edit on a file with range snippets appends stale markers."""
        from bouzecode.backend.core.tool_registry import execute_tool

        path = str(tmp_py_file)
        context_state.notes[METHODOLOGY_NOTE] = (
            f"## snippet: {path} L1-3 — \"test lines\"\n"
            "    1\tline1\n"
            "    2\tline2\n"
            "    3\tline3\n"
        )

        config = {"_context_state": context_state}

        result = execute_tool(
            "Edit",
            {"file_path": path, "old_string": "line2", "new_string": "modified_line2"},
            config,
        )

        assert "Error" not in result
        note = context_state.notes[METHODOLOGY_NOTE]
        assert f"## snippet-stale: {path} L1-3" in note

    def test_write_marks_snippet_stale(self, context_state, tmp_py_file):
        """Calling Write on a file with range snippets appends stale markers."""
        from bouzecode.backend.core.tool_registry import execute_tool

        path = str(tmp_py_file)
        context_state.notes[METHODOLOGY_NOTE] = (
            f"## snippet: {path} L1-5 — \"full file\"\n"
            "    1\tline1\n"
            "    2\tline2\n"
        )

        config = {"_context_state": context_state}

        result = execute_tool(
            "Write",
            {"file_path": path, "content": "new content\n"},
            config,
        )

        assert "Error" not in result
        note = context_state.notes[METHODOLOGY_NOTE]
        assert f"## snippet-stale: {path} L1-5" in note

    def test_failed_edit_does_not_mark_stale(self, context_state, tmp_py_file):
        """A failed Edit (old_string not found) does NOT mark snippets stale."""
        from bouzecode.backend.core.tool_registry import execute_tool

        path = str(tmp_py_file)
        context_state.notes[METHODOLOGY_NOTE] = (
            f"## snippet: {path} L1-3 — \"test\"\n"
            "    1\tline1\n"
        )

        config = {"_context_state": context_state}

        result = execute_tool(
            "Edit",
            {"file_path": path, "old_string": "NONEXISTENT", "new_string": "whatever"},
            config,
        )

        assert "Error" in result
        note = context_state.notes[METHODOLOGY_NOTE]
        assert "snippet-stale" not in note

    def test_edit_unrelated_file_no_stale(self, context_state, tmp_path):
        """Editing a file not covered by any snippet produces no stale marker."""
        from bouzecode.backend.core.tool_registry import execute_tool

        covered = tmp_path / "covered.py"
        covered.write_text("covered\n", encoding="utf-8")
        unrelated = tmp_path / "unrelated.py"
        unrelated.write_text("original\n", encoding="utf-8")

        context_state.notes[METHODOLOGY_NOTE] = (
            f"## snippet: {covered} L1-1 — \"covered file\"\n"
            "    1\tcovered\n"
        )

        config = {"_context_state": context_state}

        result = execute_tool(
            "Edit",
            {"file_path": str(unrelated), "old_string": "original", "new_string": "changed"},
            config,
        )

        assert "Error" not in result
        note = context_state.notes[METHODOLOGY_NOTE]
        assert "snippet-stale" not in note
