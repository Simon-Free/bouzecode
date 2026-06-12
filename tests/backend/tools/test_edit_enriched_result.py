# [desc] Tests for enriched Edit tool results including success context, fuzzy failure matching, and snippet exemption
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests for enriched Edit tool results including success context, fuzzy failure matching, and snippet exemption</param></tool_use> [/desc]
"""Tests for enriched Edit tool_result (success context + fuzzy failure + snippet exemption)."""

import tempfile
from pathlib import Path

from bouzecode.backend.tools.ops.file_ops import _edit


class TestEditSuccessContext:
    """On successful edit, result includes surrounding lines with line numbers."""

    def test_success_shows_context_lines(self, tmp_path):
        """After a successful edit, the result contains numbered context around the change."""
        f = tmp_path / "example.py"
        lines = [f"line {i}" for i in range(1, 31)]
        f.write_text("\n".join(lines), encoding="utf-8")

        result = _edit(str(f), "line 15", "modified_line 15")

        # Must contain the modified line
        assert "modified_line 15" in result
        # Must contain line numbers (format: "N\tline_content")
        assert "15\t" in result or "15 " in result
        # Must contain some context before and after
        assert "line 14" in result
        assert "line 16" in result

    def test_success_context_bounded(self, tmp_path):
        """Context doesn't exceed ~10 lines before/after the edit region."""
        f = tmp_path / "big.py"
        lines = [f"line {i}" for i in range(1, 101)]
        f.write_text("\n".join(lines), encoding="utf-8")

        result = _edit(str(f), "line 50", "CHANGED_50")

        # line 50 is roughly in the middle; context should NOT include line 1 or line 100
        assert "line 1\n" not in result or "1\tline 1" not in result
        assert "line 100" not in result

    def test_success_shows_enclosing_symbol(self, tmp_path):
        """If the edit is inside a function/class, the result header mentions it."""
        f = tmp_path / "mod.py"
        code = '''\
class Foo:
    def bar(self):
        old_value = 1
        return old_value

def standalone():
    pass
'''
        f.write_text(code, encoding="utf-8")

        result = _edit(str(f), "old_value = 1", "new_value = 42")

        # Should mention the enclosing symbol
        assert "Foo.bar" in result

    def test_success_large_new_string_truncated_middle(self, tmp_path):
        """When new_string is very large, the context truncates the middle."""
        f = tmp_path / "large.py"
        content = "HEADER\nREPLACE_ME\nFOOTER\n"
        f.write_text(content, encoding="utf-8")

        big_new = "\n".join(f"generated_line_{i}" for i in range(200))
        result = _edit(str(f), "REPLACE_ME", big_new)

        # Result should be bounded (not 200+ lines of context)
        result_lines = result.strip().split("\n")
        assert len(result_lines) < 60  # reasonable bound


class TestEditFailureFuzzy:
    """On failed edit (old_string not found), show fuzzy match + context."""

    def test_failure_shows_fuzzy_match(self, tmp_path):
        """Error message includes the closest matching line(s) from the file."""
        f = tmp_path / "target.py"
        content = "def hello():\n    value = 42\n    return value\n"
        f.write_text(content, encoding="utf-8")

        result = _edit(str(f), "valeu = 42", "value = 99")  # typo in old_string

        assert "Error" in result
        # Should show the closest match
        assert "value = 42" in result
        # Should show line number of the match
        assert "2" in result  # line 2

    def test_failure_shows_context_around_match(self, tmp_path):
        """Fuzzy match includes a few lines of context."""
        f = tmp_path / "ctx.py"
        lines = [f"line_{i} = {i}" for i in range(1, 21)]
        f.write_text("\n".join(lines), encoding="utf-8")

        result = _edit(str(f), "line_10 = 999", "replaced")  # wrong value

        assert "Error" in result
        # Should show nearby lines for context
        assert "line_9" in result or "line_11" in result

    def test_failure_no_crash_on_empty_file(self, tmp_path):
        """Fuzzy match on empty file doesn't crash."""
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")

        result = _edit(str(f), "something", "other")

        assert "Error" in result


class TestEditSnippetExemption:
    """Edit results must NEVER be marked as snippetable."""

    def test_edit_result_not_wrapped_with_snippet_markers(self, tmp_path):
        """Even if result exceeds SNIPPET_MIN_LINES, no snippet markers present."""
        from bouzecode.backend.agent.snippet_wire import (
            _SNIPPET_OPEN, _SNIPPET_CLOSE, wrap_snippetable,
            is_snippetable_tool_id,
        )

        # Edit tool should not be snippetable
        assert is_snippetable_tool_id("Edit") is False

        # Double-check: even a large edit result should not get markers
        f = tmp_path / "big.py"
        lines = [f"line {i}" for i in range(1, 200)]
        f.write_text("\n".join(lines), encoding="utf-8")

        result = _edit(str(f), "line 100", "MODIFIED_100")

        assert "A SNIPPETER" not in result
        assert _SNIPPET_CLOSE not in result
