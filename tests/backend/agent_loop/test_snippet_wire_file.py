"""Tests for file-keyed snippet wire wrapping (Read/Skill markers)."""
import pytest

from bouzecode.backend.agent.snippet_wire import (
    is_file_snippetable,
    wrap_file_snippetable,
    is_snippetable_tool_id,
    wrap_snippetable,
    SNIPPET_MIN_LINES,
)


# Helper: generate content with exactly N lines
def _content_with_lines(n: int) -> str:
    return "\n".join(f"line{i}" for i in range(1, n + 1))


class TestIsFileSnippetable:
    def test_read_is_file_snippetable(self):
        assert is_file_snippetable("Read") is True

    def test_skill_is_file_snippetable(self):
        assert is_file_snippetable("Skill") is True

    def test_grep_not_file_snippetable(self):
        # Grep is tool_id-snippetable, not file-snippetable
        assert is_file_snippetable("Grep") is False

    def test_edit_not_snippetable(self):
        assert is_file_snippetable("Edit") is False

    def test_none_not_snippetable(self):
        assert is_file_snippetable(None) is False

    def test_empty_not_snippetable(self):
        assert is_file_snippetable("") is False


class TestWrapFileSnippetable:
    """wrap_file_snippetable only wraps content >= SNIPPET_MIN_LINES."""

    def test_small_content_returned_as_is(self):
        """Content below threshold is returned unchanged (no markers)."""
        content = "line1\nline2\nline3"
        result = wrap_file_snippetable(content, "/abs/path/foo.py")
        assert result == content
        assert "A SNIPPETER" not in result

    def test_empty_content_returned_as_is(self):
        result = wrap_file_snippetable("", "/some/file.py")
        assert result == ""
        assert "A SNIPPETER" not in result

    def test_single_line_returned_as_is(self):
        result = wrap_file_snippetable("hello world", "/x.py")
        assert result == "hello world"
        assert "A SNIPPETER" not in result

    def test_at_threshold_is_wrapped(self):
        """Content with exactly SNIPPET_MIN_LINES lines IS wrapped."""
        content = _content_with_lines(SNIPPET_MIN_LINES)
        result = wrap_file_snippetable(content, "/abs/path/foo.py")
        assert "==== A SNIPPETER id: file=/abs/path/foo.py ====" in result
        assert "==== FIN DE L'ELEMENT A SNIPPETER ====" in result
        assert 'Snippet(file_path="/abs/path/foo.py"' in result
        # Lines are numbered
        assert "1\tline1" in result
        assert f"{SNIPPET_MIN_LINES}\tline{SNIPPET_MIN_LINES}" in result

    def test_above_threshold_is_wrapped(self):
        """Content above threshold is wrapped with markers."""
        content = _content_with_lines(SNIPPET_MIN_LINES + 10)
        result = wrap_file_snippetable(content, "/big/file.py")
        assert "==== A SNIPPETER id: file=/big/file.py ====" in result
        assert "==== FIN DE L'ELEMENT A SNIPPETER ====" in result


class TestToolIdSnippetableUnchanged:
    """Ensure existing tool_id wrapping respects the threshold too."""

    def test_small_content_not_wrapped(self):
        content = "abc\ndef"
        result = wrap_snippetable(content, "r1")
        assert result == content
        assert "A SNIPPETER" not in result

    def test_wrap_snippetable_format_above_threshold(self):
        content = _content_with_lines(SNIPPET_MIN_LINES)
        result = wrap_snippetable(content, "r1")
        assert "==== A SNIPPETER id: tool_id=r1 ====" in result
        assert "==== FIN DE L'ELEMENT A SNIPPETER ====" in result
        assert "1\tline1" in result
        assert f"{SNIPPET_MIN_LINES}\tline{SNIPPET_MIN_LINES}" in result
