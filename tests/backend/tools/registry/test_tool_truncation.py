# [desc] Tests truncate_tool_output function for capping large Bash/test outputs and saving full content to file
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests truncate_tool_output function for capping large Bash/test outputs and saving full content to file</param></tool_use> [/desc]
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
