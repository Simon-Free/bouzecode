# [desc] E2E tests verifying token optimization features: Edit/Write compaction, GFD max_depth, Bash truncation. [/desc]
"""E2E tests for token optimization features.

Tests the 4 optimizations:
1. Edit/Write tool results are compacted (no diff echo in messages)
2. GetFolderDescription respects max_depth=2 by default
3. Bash/RunPythonTest output is truncated when too large
4. CODE_DISCOVERY_PROMPT is included in system prompt
"""

import os
import tempfile
from pathlib import Path

import pytest
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode

# Every mock response must include Methodology to satisfy enforcement hooks
METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
NO_TEST_ENFORCE = {"enforce_tests": False}


class TestEditCompactResult:
    """Edit tool results stored in state.messages should be compact (no diff)."""

    def test_edit_result_in_messages_is_compact(self, tmp_path):
        """When Edit runs, the tool_result in messages is compact (✓ + filename)."""
        target = tmp_path / "temp_greet.py"
        target.write_text("def hello():\n    return 'hello'\n", encoding="utf-8")

        mock = MockLLM([
            f'{METH}<tool_use name="Edit" id="e1"><param name="file_path">{target}</param>'
            '<param name="old_string">return \'hello\'</param>'
            '<param name="new_string">return \'world\'</param></tool_use>',
            f"Done editing.\n{METH}",
        ])
        result = bouzecode(["edit the file"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

        edit_results = [
            m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "Edit"
        ]
        assert edit_results, "No Edit tool result found in messages"

        content = edit_results[0]["content"]
        assert content.startswith("\u2713"), f"Expected compact result starting with ✓, got: {content!r}"
        assert "temp_greet.py" in content
        assert "---" not in content
        assert "+++" not in content
        assert "@@" not in content

    def test_edit_error_preserved_in_messages(self, tmp_path):
        """Edit errors are NOT compacted — kept verbatim for debugging."""
        target = tmp_path / "temp_missing.py"
        target.write_text("content\n", encoding="utf-8")

        mock = MockLLM([
            f'{METH}<tool_use name="Edit" id="e1"><param name="file_path">{target}</param>'
            '<param name="old_string">NONEXISTENT STRING</param>'
            '<param name="new_string">replacement</param></tool_use>',
            f"Got an error.\n{METH}",
        ])
        result = bouzecode(["edit"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

        edit_results = [
            m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "Edit"
        ]
        assert edit_results
        content = edit_results[0]["content"]
        assert "Error" in content
        assert "old_string not found" in content

    def test_write_existing_file_compact(self, tmp_path):
        """Write to existing file produces compact result (no diff)."""
        target = tmp_path / "data.txt"
        target.write_text("original\n", encoding="utf-8")

        mock = MockLLM([
            f'{METH}<tool_use name="Write" id="w1"><param name="file_path">{target}</param>'
            '<param name="content">updated content\n</param></tool_use>',
            f"Written.\n{METH}",
        ])
        result = bouzecode(["write file"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

        write_results = [
            m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "Write"
        ]
        assert write_results
        content = write_results[0]["content"]
        assert "data.txt" in content
        assert "---" not in content
        assert "+++" not in content


class TestGFDMaxDepth:
    """GetFolderDescription respects max_depth parameter."""

    @pytest.fixture(autouse=True)
    def _enable_gfd(self):
        from bouzecode.backend.core.tool_registry import enable_tool
        enable_tool("GetFolderDescription")

    def test_default_depth_excludes_deep_files(self, tmp_path, monkeypatch):
        """Default max_depth=2 excludes files at depth 3+."""
        monkeypatch.setattr(
            "bouzecode.backend.tools.folder_desc.analyzer._call_llm_for_description",
            lambda *a, **k: "stub description",
        )
        deep_dir = tmp_path / "project" / "a" / "b" / "c"
        deep_dir.mkdir(parents=True)
        (deep_dir / "deep.py").write_text("# deep file\n", encoding="utf-8")
        (tmp_path / "project" / "a").mkdir(exist_ok=True)
        (tmp_path / "project" / "a" / "shallow.py").write_text("# shallow\n", encoding="utf-8")
        (tmp_path / "project" / "top.py").write_text("# top\n", encoding="utf-8")

        folder = str(tmp_path / "project")
        mock = MockLLM([
            f'{METH}<tool_use name="GetFolderDescription" id="g1">'
            f'<param name="folder_path">{folder}</param></tool_use>',
            f"Done exploring.\n{METH}",
        ])
        result = bouzecode(["describe folder"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

        gfd_results = [
            m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "GetFolderDescription"
        ]
        assert gfd_results
        content = gfd_results[0]["content"]
        assert "top.py" in content
        assert "shallow.py" in content
        assert "deep.py" not in content
        assert "not shown" in content.lower() or "deeper" in content.lower()

    def test_explicit_high_depth_includes_all(self, tmp_path, monkeypatch):
        """Explicit max_depth=5 includes deep files."""
        monkeypatch.setattr(
            "bouzecode.backend.tools.folder_desc.analyzer._call_llm_for_description",
            lambda *a, **k: "stub description",
        )
        deep_dir = tmp_path / "proj" / "a" / "b" / "c"
        deep_dir.mkdir(parents=True)
        (deep_dir / "deep.py").write_text("# deep\n", encoding="utf-8")
        (tmp_path / "proj" / "top.py").write_text("# top\n", encoding="utf-8")

        folder = str(tmp_path / "proj")
        mock = MockLLM([
            f'{METH}<tool_use name="GetFolderDescription" id="g1">'
            f'<param name="folder_path">{folder}</param>'
            '<param name="max_depth">5</param></tool_use>',
            f"All visible.\n{METH}",
        ])
        result = bouzecode(["describe all"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

        gfd_results = [
            m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "GetFolderDescription"
        ]
        assert gfd_results
        content = gfd_results[0]["content"]
        assert "deep.py" in content
        assert "top.py" in content


class TestBashTruncation:
    """Bash output is truncated when too large, with full output saved to file."""

    def test_short_output_not_truncated(self, tmp_path):
        """Short Bash output (< threshold) is returned verbatim."""
        mock = MockLLM([
            f'{METH}<tool_use name="Bash" id="b1"><param name="command">echo hello</param></tool_use>',
            f"Got output.\n{METH}",
        ])
        result = bouzecode(["echo"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

        bash_results = [
            m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "Bash"
        ]
        assert bash_results
        content = bash_results[0]["content"]
        assert "hello" in content
        assert "truncated" not in content.lower()

    def test_long_output_truncated(self, tmp_path):
        """Long Bash output is truncated with a pointer to the full file."""
        big_file = tmp_path / "big_output.txt"
        lines = [f"Line number {i}" for i in range(300)]
        big_file.write_text("\n".join(lines), encoding="utf-8")

        mock = MockLLM([
            f'{METH}<tool_use name="Bash" id="b1"><param name="command">type "{big_file}"</param></tool_use>',
            f"Got truncated output.\n{METH}",
        ])
        result = bouzecode(["read big file"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

        bash_results = [
            m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "Bash"
        ]
        assert bash_results
        content = bash_results[0]["content"]
        assert "truncated" in content.lower()
        assert "Line number 0" in content
        assert "Read" in content or "file_path" in content
        assert "Line number 299" not in content


class TestCodeDiscoveryPrompt:
    """Code discovery now lives in the default (code) agent profile, layered on top of
    the agnostic noyau and injected at depth 0 by dispatch — not in the shared base."""

    @pytest.mark.skip(reason="Requires .bouzecode/profiles/ YAML (not in OSS worktree)")
    def test_code_discovery_in_default_profile(self):
        """The default profile carries the Code Discovery section; the noyau does not."""
        from bouzecode.backend.profiles import load_profiles_from_dir
        from bouzecode.backend.core.context import build_system_prompt_parts

        repo_root = Path(__file__).resolve().parents[4]
        profiles = load_profiles_from_dir(repo_root / ".bouzecode" / "profiles")
        extra = profiles["default"].system_prompt_extra

        assert "Découverte de code" in extra
        assert "GetFolderDescription" in extra
        assert "Glob" in extra or "Grep" in extra
        # Separation of concerns: the code-discovery section is NOT in the shared noyau.
        assert "Découverte de code" not in build_system_prompt_parts()[0]
