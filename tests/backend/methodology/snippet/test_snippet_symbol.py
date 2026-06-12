# [desc] Tests for Snippet(symbol=...) dynamic symbol-based snippets: resolution, refresh, caching, and tool integration
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests for Snippet(symbol=...) dynamic symbol-based snippets: resolution, refresh, caching, and tool integration</param></tool_use> [/desc]
"""Tests for Snippet(symbol=...) — dynamic symbol-based snippets."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from bouzecode.backend.context_manager.methodology import snippet_tool
from bouzecode.backend.context_manager.methodology import build_methodology_system_blocks
from bouzecode.backend.context_manager.snippet_resolve import (
    resolve_snippet_symbol,
    refresh_symbol_snippets,
)
from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE


def _config(state=None) -> dict:
    return {"_context_state": state or ContextState(), "_state": None}


# --- resolve_snippet_symbol unit tests ---


def test_resolve_snippet_symbol_basic():
    """Resolves a top-level function symbol."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "mod.py"
        f.write_text("import os\n\ndef hello():\n    return 42\n\ndef bye():\n    pass\n", encoding="utf-8")
        result = resolve_snippet_symbol(str(f), "hello", "greeting")
        assert "## snippet:" in result
        assert ":: hello" in result
        assert "greeting" in result
        assert "return 42" in result
        assert "bye" not in result


def test_resolve_snippet_symbol_class_method():
    """Resolves a Class.method symbol."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "cls.py"
        f.write_text(
            "class Foo:\n    def bar(self):\n        return 1\n\n    def baz(self):\n        return 2\n",
            encoding="utf-8",
        )
        result = resolve_snippet_symbol(str(f), "Foo.bar")
        assert ":: Foo.bar" in result
        assert "return 1" in result
        assert "return 2" not in result


def test_resolve_snippet_symbol_not_found():
    """Returns error block when symbol doesn't exist."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "empty.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = resolve_snippet_symbol(str(f), "nonexistent")
        assert "snippet ERROR" in result
        assert "symbol not found" in result


def test_resolve_snippet_symbol_relative_path_error():
    """Relative path returns error."""
    result = resolve_snippet_symbol("relative/file.py", "func")
    assert "snippet ERROR" in result
    assert "must be absolute" in result


def test_resolve_snippet_symbol_missing_file_error():
    """Missing file returns error."""
    missing = str(Path(tempfile.gettempdir()).resolve() / "no_such_file_xyz.py")
    result = resolve_snippet_symbol(missing, "func")
    assert "snippet ERROR" in result
    assert "file not found" in result


# --- refresh_symbol_snippets unit tests ---


def test_refresh_symbol_snippets_no_change():
    """When source hasn't changed, methodology text is identical."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "stable.py"
        f.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
        # Build initial snippet
        block = resolve_snippet_symbol(str(f), "greet", "stable")
        methodology = f"## some prior content\n{block}"
        refreshed = refresh_symbol_snippets(methodology)
        assert refreshed == methodology


def test_refresh_symbol_snippets_detects_change():
    """When source changes, the snippet body is updated."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "evolve.py"
        f.write_text("def calc():\n    return 1\n", encoding="utf-8")
        block = resolve_snippet_symbol(str(f), "calc")
        methodology = f"## header\n{block}"

        # Modify source
        f.write_text("def calc():\n    return 999\n", encoding="utf-8")
        refreshed = refresh_symbol_snippets(methodology)

        assert "return 999" in refreshed
        assert "return 1" not in refreshed
        assert refreshed != methodology


def test_refresh_symbol_snippets_file_deleted_keeps_stale():
    """If file disappears, the old block is preserved (not errored)."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "gone.py"
        f.write_text("def x():\n    pass\n", encoding="utf-8")
        block = resolve_snippet_symbol(str(f), "x")
        methodology = f"## notes\n{block}"

    # File is gone (tempdir cleaned up)
    refreshed = refresh_symbol_snippets(methodology)
    assert refreshed == methodology  # unchanged


def test_refresh_symbol_snippets_symbol_removed_keeps_stale():
    """If symbol is removed from file, the old block is preserved."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "shrink.py"
        f.write_text("def old_func():\n    pass\n", encoding="utf-8")
        block = resolve_snippet_symbol(str(f), "old_func")
        methodology = f"## notes\n{block}"

        # Remove the symbol from file
        f.write_text("# nothing here\n", encoding="utf-8")
        refreshed = refresh_symbol_snippets(methodology)

        assert refreshed == methodology  # kept stale


def test_refresh_preserves_range_based_snippets():
    """Range-based snippets (L<a>-<b>) are NOT touched by refresh."""
    methodology = (
        "## snippet: /some/path.py L10-20 — \"label\"\n"
        "   10  def foo():\n"
        "   11      pass\n"
    )
    refreshed = refresh_symbol_snippets(methodology)
    assert refreshed == methodology


# --- snippet_tool integration (symbol param) ---


def test_snippet_tool_symbol_appends_to_methodology():
    """snippet_tool with symbol param appends a dynamic snippet block."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "src.py"
        f.write_text("class Config:\n    def load(self):\n        return {}\n", encoding="utf-8")
        cfg = _config()
        result = snippet_tool({"file_path": str(f), "symbol": "Config.load", "label": "loader"}, cfg)
        note = cfg["_context_state"].notes[METHODOLOGY_NOTE]

        assert "snippet appended: symbol 'Config.load'" in result
        assert ":: Config.load" in note
        assert "loader" in note
        assert "return {}" in note


def test_snippet_tool_symbol_missing_file_path_error():
    """symbol without file_path returns error."""
    cfg = _config()
    result = snippet_tool({"symbol": "func", "tool_id": "t1"}, cfg)
    assert "Error" in result
    assert "'symbol' requires 'file_path'" in result


def test_snippet_tool_symbol_not_found_captures_error():
    """If symbol not found, error is captured in methodology."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "no_sym.py"
        f.write_text("x = 1\n", encoding="utf-8")
        cfg = _config()
        result = snippet_tool({"file_path": str(f), "symbol": "missing"}, cfg)
        assert "snippet ERROR" in result
        assert "symbol not found" in cfg["_context_state"].notes[METHODOLOGY_NOTE]


def test_snippet_tool_symbol_discard_without_symbol_or_ranges():
    """discard=True without ranges or symbol discards."""
    cfg = _config()
    result = snippet_tool({"file_path": "/abs/f.py", "discard": True}, cfg)
    assert "discarded" in result


def test_snippet_tool_symbol_discard_ignored_when_symbol_given():
    """When symbol is provided, discard is ignored and snippet saved."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "d.py"
        f.write_text("def func():\n    pass\n", encoding="utf-8")
        cfg = _config()
        result = snippet_tool({"file_path": str(f), "symbol": "func", "discard": True}, cfg)
        assert "appended" in result
        assert ":: func" in cfg["_context_state"].notes[METHODOLOGY_NOTE]


# --- build_methodology_system_blocks integration ---


def test_build_methodology_refreshes_symbol_snippets():
    """build_methodology_system_blocks re-resolves symbol snippets."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "live.py"
        f.write_text("def compute():\n    return 'v1'\n", encoding="utf-8")
        block = resolve_snippet_symbol(str(f), "compute")
        methodology = f"## Goal: test\n{block}"

        # Modify source
        f.write_text("def compute():\n    return 'v2'\n", encoding="utf-8")

        blocks, delta = build_methodology_system_blocks(methodology, "", {})
        text = blocks[0]["text"]
        assert "return 'v2'" in text
        assert "return 'v1'" not in text


def test_build_methodology_cache_stable_when_no_change():
    """If source unchanged, the prefix cache remains valid."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "stable2.py"
        f.write_text("def s():\n    return 0\n", encoding="utf-8")
        block = resolve_snippet_symbol(str(f), "s")
        methodology = f"## Intro\n{block}"

        # Use methodology as snapshot (simulates previous cache)
        blocks, delta = build_methodology_system_blocks(methodology, methodology, {})
        # delta should be empty — full text matches snapshot
        assert delta == ""
