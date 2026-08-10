# [desc] Tests truncate_tool_output function for capping large Bash/test outputs and saving full content to file [/desc]
"""Test tool output truncation for Bash and RunPythonTest."""

from pathlib import Path

from bouzecode.backend.tools.ops.truncation import truncate_tool_output


class TestTruncateToolOutput:
    """truncate_tool_output caps large outputs and saves full to file."""

    def test_short_output_unchanged(self):
        output = "line1\nline2\nline3"
        result = truncate_tool_output(output, "Bash")
        assert result == output

    def test_long_output_truncated_by_lines(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path))
        lines = [f"line {i}" for i in range(500)]
        output = "\n".join(lines)

        result = truncate_tool_output(output, "Bash", max_lines=200, head_lines=80)
        # Should contain first 80 lines
        assert "line 0" in result
        assert "line 79" in result
        # Should NOT contain line 200+
        assert "line 200" not in result
        # Should contain truncation message
        assert "truncated" in result.lower()
        assert "500" in result  # total lines mentioned
        assert "Read(file_path=" in result

    def test_long_output_truncated_by_chars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path))
        # 50 lines but each very long
        lines = ["x" * 200 for _ in range(50)]
        output = "\n".join(lines)  # 50 lines, 10000+ chars

        result = truncate_tool_output(output, "Bash", max_lines=200, max_chars=8000, head_lines=80)
        assert "truncated" in result.lower()

    def test_saved_file_contains_full_output(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path))
        lines = [f"line {i}" for i in range(500)]
        output = "\n".join(lines)

        result = truncate_tool_output(output, "Bash", max_lines=200, head_lines=80)
        # Extract file path from result
        import re
        match = re.search(r'Read\(file_path="([^"]+)"\)', result)
        assert match, f"No file path in result: {result}"
        saved_path = Path(match.group(1))
        assert saved_path.exists()
        saved_content = saved_path.read_text(encoding="utf-8")
        assert "line 499" in saved_content
        assert saved_content.strip() == output.strip()

    def test_non_truncated_no_file_created(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path))
        output = "short output"
        truncate_tool_output(output, "Bash", max_lines=200, head_lines=80)
        # No files should be created
        assert list(tmp_path.iterdir()) == []

    def test_tail_preserves_pytest_verdict(self, tmp_path, monkeypatch):
        """The model MUST see the LAST line (test verdict), not just the head.

        Real-world bug: browser pytest runs emit hundreds of werkzeug log lines
        BEFORE the final summary. Head-only truncation hid the verdict, so the
        model believed its tests passed when they failed.
        """
        monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path))
        verdict = "==== 4 failed, 2 passed in 121s ===="
        lines = [f"werkzeug log line {i}" for i in range(399)] + [verdict]
        output = "\n".join(lines)  # 400 lines, verdict is the last one

        result = truncate_tool_output(
            output, "RunPythonTest", max_lines=200, head_lines=80, tail_lines=160
        )
        # Head present
        assert "werkzeug log line 0" in result
        # Verdict (tail) present — the whole point of this fix
        assert verdict in result
        # Middle cut away
        assert "werkzeug log line 200" not in result
        # Truncation marker sits in the MIDDLE, before the tail
        assert "truncated" in result.lower()
        assert result.index("truncated") < result.index(verdict)

    def test_tail_pointer_still_resolvable(self, tmp_path, monkeypatch):
        """The overflow pointer stays resolvable even with the marker mid-text."""
        from bouzecode.web_v2.services.sessions.formatter import (
            resolve_overflow_pointer,
        )

        monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path))
        lines = [f"line {i}" for i in range(399)] + ["==== 4 failed ===="]
        output = "\n".join(lines)

        result = truncate_tool_output(
            output, "Bash", max_lines=200, head_lines=80, tail_lines=160
        )
        path = resolve_overflow_pointer(result)
        assert path is not None
        assert Path(path).exists()

    def test_head_plus_tail_covers_all_no_line_duplication(self, tmp_path, monkeypatch):
        """When head+tail >= total lines, no line is duplicated but marker stays."""
        monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path))
        # 50 short lines but each huge → over char limit, under line limit split
        lines = [f"row {i} " + "x" * 300 for i in range(50)]
        output = "\n".join(lines)

        result = truncate_tool_output(
            output, "Bash", max_lines=200, max_chars=8000, head_lines=80, tail_lines=160
        )
        # Every original line appears exactly once (no duplication)
        for i in range(50):
            assert result.count(f"row {i} ") == 1
        # Marker still present so the full file remains reachable
        assert "truncated" in result.lower()
