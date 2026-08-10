# [desc] Tests that Edit tool_result shows context on success and fuzzy match on failure. [/desc]
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


class TestEditWriteSnippetable:
    """Edit/Write results are file-keyed snippetable (like Read/Skill)."""

    def test_edit_write_are_file_snippetable(self):
        """is_file_snippetable is True for Edit and Write."""
        from bouzecode.backend.agent.snippet_wire import is_file_snippetable

        assert is_file_snippetable("Edit") is True
        assert is_file_snippetable("Write") is True

    def test_edit_write_not_tool_id_snippetable(self):
        """Edit/Write use the file-keyed path, NOT the registry tool_id path."""
        from bouzecode.backend.agent.snippet_wire import is_snippetable_tool_id

        assert is_snippetable_tool_id("Edit") is False
        assert is_snippetable_tool_id("Write") is False

    def test_large_edit_result_wrapped_by_payload(self, tmp_path):
        """A large Edit result (>=50 lines) is wrapped with file= markers by build_minimal_payload.

        Decoupled from _edit's diff truncation: we feed a synthetic >=50-line
        tool_result directly, so this exercises build_minimal_payload's wrap path
        (is_file_snippetable + file_path_index + line threshold), not file_ops.
        """
        from bouzecode.backend.agent.snippet_wire import _SNIPPET_CLOSE
        from bouzecode.backend.agent.minimal_payload import build_minimal_payload

        f = tmp_path / "big.py"
        # Synthetic Edit result with >=50 lines so it crosses SNIPPET_MIN_LINES.
        result = "Changes applied to big.py:\n\n" + "\n".join(
            f"+new line {i}" for i in range(1, 60)
        )

        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "ed1", "name": "Edit",
                             "input": {"file_path": str(f), "old_string": "x",
                                       "new_string": "y"}}]},
            {"role": "tool", "tool_call_id": "ed1", "name": "Edit", "content": result},
        ]
        wire = build_minimal_payload(messages)
        tool_msg = next(m for m in wire if m.get("role") == "tool")
        assert f"A SNIPPETER id: file={f}" in tool_msg["content"]
        assert _SNIPPET_CLOSE in tool_msg["content"]

    def test_edit_write_tracked_by_enforcement(self, tmp_path):
        """get_unsnippeted_reads reports an un-snippeted large Edit result as file-keyed."""
        from bouzecode.backend.tools.enforcement_hooks import get_unsnippeted_reads

        f = tmp_path / "big.py"
        big_content = "\n".join(f"line {i}" for i in range(1, 60))

        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "ed1", "name": "Edit",
                             "input": {"file_path": str(f), "old_string": "x",
                                       "new_string": "y"}},
                            {"id": "m1", "name": "Methodology",
                             "input": {"content": "note"}}]},
            {"role": "tool", "tool_call_id": "ed1", "name": "Edit", "content": big_content},
            # A following assistant turn exists -> timing guard does NOT defer.
            {"role": "assistant", "content": "next"},
        ]
        unsnippeted = get_unsnippeted_reads(messages)
        assert any(
            r["kind"] == "file" and r["key"] == str(f) and r["tool_name"] == "Edit"
            for r in unsnippeted
        )
