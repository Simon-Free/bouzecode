# [desc] Tests that the Methodology tool is append-only and never replaces existing content including snippets
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that the Methodology tool is append-only and never replaces existing content including snippets</param></tool_use> [/desc]
"""Test that Methodology tool is append-only (no replace mode)."""
from bouzecode.backend.context_manager.methodology import methodology_tool, METHODOLOGY_NOTE


def _make_config(initial_notes=""):
    """Create a minimal config dict with context_state."""
    class FakeContextState:
        def __init__(self):
            self.notes = {}
            if initial_notes:
                self.notes[METHODOLOGY_NOTE] = initial_notes
    context_state = FakeContextState()
    return {"_context_state": context_state, "_state": type("S", (), {"notes_timeline": []})()}


def test_append_basic():
    config = _make_config()
    result = methodology_tool({"content": "hello"}, config)
    assert "append" in result
    assert config["_context_state"].notes[METHODOLOGY_NOTE] == "hello"


def test_append_joins_with_double_newline():
    config = _make_config("existing content")
    methodology_tool({"content": "new content"}, config)
    assert config["_context_state"].notes[METHODOLOGY_NOTE] == "existing content\n\nnew content"


def test_replace_mode_still_appends():
    """Key regression test: mode='replace' must NOT wipe existing content."""
    config = _make_config("## User @2026-01-01\nUser said something\n\n## snippet: file.py\ncode here")
    methodology_tool({"mode": "replace", "content": "new stuff"}, config)
    notes = config["_context_state"].notes[METHODOLOGY_NOTE]
    # All original content must still be present
    assert "## User @2026-01-01" in notes
    assert "User said something" in notes
    assert "## snippet: file.py" in notes
    assert "code here" in notes
    # New content appended
    assert "new stuff" in notes


def test_replace_mode_preserves_snippets():
    """Snippets must never be wiped by mode='replace'."""
    original = "## Plan\nDo X\n\n## snippet: foo.py L1-10\n  1  import os"
    config = _make_config(original)
    methodology_tool({"mode": "replace", "content": "## New plan"}, config)
    notes = config["_context_state"].notes[METHODOLOGY_NOTE]
    assert "## snippet: foo.py" in notes
    assert "import os" in notes
    assert "## New plan" in notes


def test_empty_content_no_change():
    config = _make_config("existing")
    methodology_tool({"content": ""}, config)
    assert config["_context_state"].notes[METHODOLOGY_NOTE] == "existing"


def test_no_context_state_returns_error():
    result = methodology_tool({"content": "hello"}, {})
    assert "Error" in result
