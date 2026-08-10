# [desc] Tests that Edit/Write tool results are compacted (diffs stripped) before entering state messages. [/desc]
"""Test that Edit/Write tool results are compacted before entering state.messages."""

import tempfile
from pathlib import Path

from bouzecode.backend.tools.ops.file_ops import _edit, _write
from bouzecode.backend.agent.loop_turn import _compact_tool_result


class TestCompactEditResult:
    """_compact_tool_result strips diff from Edit results."""

    def test_edit_result_diff_preserved(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("old line\n", encoding="utf-8")

        full_result = _edit(str(f), "old line", "new line")
        assert "---" in full_result  # sanity: full diff present
        assert "+new line" in full_result

        # Edit is no longer compacted — the full diff is preserved so the
        # result can be file-snippeted like a Read.
        compact = _compact_tool_result("Edit", full_result)
        assert compact == full_result
        assert "+new line" in compact
        assert "-old line" in compact

    def test_edit_error_preserved(self):
        result = "Error: old_string not found in file."
        compact = _compact_tool_result("Edit", result)
        assert compact == result

    def test_write_existing_file_compacted(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("alpha\n", encoding="utf-8")

        full_result = _write(str(f), "beta\n")
        assert "---" in full_result or "File updated" in full_result

        # Write is no longer compacted — full diff preserved for file-snippeting.
        compact = _compact_tool_result("Write", full_result)
        assert compact == full_result

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
