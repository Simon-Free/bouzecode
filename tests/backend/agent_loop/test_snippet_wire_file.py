"""Tests for file-keyed snippet wire marking (Read/Skill): numbered result, instruction apart
(it rides in <harness_notes> since 2026-10-07, never inside the tool_result)."""
import pytest

from bouzecode.backend.agent.snippet_wire import (
    is_file_snippetable,
    mark_file_snippetable,
    is_snippetable_tool_id,
    mark_snippetable,
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

    def test_edit_is_file_snippetable(self):
        # Contract shipped on this chantier: Edit/Write are now file-keyed
        # snippetable so their post-edit diff can be frozen like a Read
        # (snippet_wire._FILE_SNIPPET_TOOLS = {Read, Skill, Edit, Write}).
        assert is_file_snippetable("Edit") is True

    def test_none_not_snippetable(self):
        assert is_file_snippetable(None) is False

    def test_empty_not_snippetable(self):
        assert is_file_snippetable("") is False


class TestMarkFileSnippetable:
    """mark_file_snippetable only marks content >= SNIPPET_MIN_LINES."""

    def test_small_content_returned_as_is(self):
        """Content below threshold is returned unchanged, with no instruction."""
        content = "line1\nline2\nline3"
        assert mark_file_snippetable(content, "/abs/path/foo.py", "r1") == (content, "")

    def test_empty_content_returned_as_is(self):
        assert mark_file_snippetable("", "/some/file.py", "r1") == ("", "")

    def test_single_line_returned_as_is(self):
        assert mark_file_snippetable("hello world", "/x.py", "r1") == ("hello world", "")

    def test_at_threshold_is_marked(self):
        """Content with exactly SNIPPET_MIN_LINES lines IS marked: numbered lines in the
        result, the instruction (key, tool id, Snippet call) apart."""
        content = _content_with_lines(SNIPPET_MIN_LINES)
        result, instruction = mark_file_snippetable(content, "/abs/path/foo.py", "r1")
        assert "A SNIPPETER id: file=/abs/path/foo.py" in instruction and "r1" in instruction
        assert 'Snippet(file_path="/abs/path/foo.py"' in instruction
        assert "SNIPPETER" not in result and "[SYSTEM]" not in result
        # Lines are numbered
        assert result.startswith("1\tline1")
        assert result.endswith(f"{SNIPPET_MIN_LINES}\tline{SNIPPET_MIN_LINES}")

    def test_above_threshold_is_marked(self):
        content = _content_with_lines(SNIPPET_MIN_LINES + 10)
        _, instruction = mark_file_snippetable(content, "/big/file.py", "r1")
        assert "A SNIPPETER id: file=/big/file.py" in instruction


class TestToolIdSnippetableUnchanged:
    """Ensure tool_id marking respects the threshold too."""

    def test_small_content_not_marked(self):
        content = "abc\ndef"
        assert mark_snippetable(content, "r1") == (content, "")

    def test_mark_snippetable_format_above_threshold(self):
        content = _content_with_lines(SNIPPET_MIN_LINES)
        result, instruction = mark_snippetable(content, "r1")
        assert "A SNIPPETER id: tool_id=r1" in instruction
        assert 'Snippet(tool_id="r1", ranges=[[a,b]])' in instruction
        assert result.startswith("1\tline1")
        assert result.endswith(f"{SNIPPET_MIN_LINES}\tline{SNIPPET_MIN_LINES}")
