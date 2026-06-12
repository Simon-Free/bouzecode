# [desc] Tests that Edit/Write tool results are compacted (diff stripped) before entering state.messages
# <tool_use name="FinalAnswer" id="x1"><param name="answer">Tests that Edit/Write tool results are compacted (diff stripped) before entering state.messages</param></tool_use> [/desc]
"""Test that Edit/Write tool results are compacted before entering state.messages."""

import tempfile
from pathlib import Path

from bouzecode.backend.tools.ops.file_ops import _edit, _write
from bouzecode.backend.agent.loop_turn import _compact_tool_result


class TestCompactEditResult:
    """_compact_tool_result strips diff from Edit results."""

    def test_edit_result_compacted(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("old line\n", encoding="utf-8")

        full_result = _edit(str(f), "old line", "new line")
        assert "---" in full_result  # sanity: full diff present
        assert "+new line" in full_result

        compact = _compact_tool_result("Edit", full_result)
        assert compact.startswith("\u2713")
        assert "hello.py" in compact
        assert "---" not in compact
        assert "+++" not in compact
        assert "@@" not in compact
        assert "+new line" not in compact
        assert "-old line" not in compact

    def test_edit_error_preserved(self):
        result = "Error: old_string not found in file."
        compact = _compact_tool_result("Edit", result)
        assert compact == result

    def test_write_existing_file_compacted(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("alpha\n", encoding="utf-8")

        full_result = _write(str(f), "beta\n")
        assert "---" in full_result or "File updated" in full_result

        compact = _compact_tool_result("Write", full_result)
        assert "data.txt" in compact
        assert "---" not in compact
        assert "+++" not in compact

    def test_write_new_file_unchanged(self, tmp_path):
        f = tmp_path / "brand_new.py"
        full_result = _write(str(f), "print('hi')\n")
        assert "Created" in full_result

        compact = _compact_tool_result("Write", full_result)
        assert compact == full_result  # already minimal

    def test_other_tool_unchanged(self):
        result = "some bash output\nwith lines"
        compact = _compact_tool_result("Bash", result)
        assert compact == result
