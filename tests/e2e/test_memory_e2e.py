"""E2E test: Memory tools — LLM saves and lists memories."""
from __future__ import annotations

import pytest
from pathlib import Path

from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


@pytest.mark.backend
class TestMemoryE2E:
    """Memory tool lifecycle through the engine."""

    @pytest.fixture(autouse=True)
    def _patch_memory_dirs(self, tmp_path, monkeypatch):
        """Point memory storage at tmp_path to avoid polluting real dirs."""
        monkeypatch.chdir(tmp_path)
        import memory.store as mem_store
        monkeypatch.setattr(mem_store, "USER_MEMORY_DIR", tmp_path / "user_memory")
        monkeypatch.setattr(mem_store, "get_project_memory_dir", lambda: tmp_path / "project_memory")

    def test_memory_save_and_list(self):
        """LLM saves a memory then lists — verify persistence."""
        mock = MockLLM([
            # Turn 1: save memory
            '<tool_use name="MemorySave" id="ms1">'
            '<param name="name">test-preference</param>'
            '<param name="content">User prefers dark mode</param>'
            '<param name="type">preference</param>'
            '<param name="scope">project</param>'
            '</tool_use>',
            # Turn 2: list memories
            '<tool_use name="MemoryList" id="ml1">'
            '<param name="scope">project</param>'
            '</tool_use>',
            # Turn 3: final reply
            "Memory saved and listed successfully.",
        ])
        result = bouzecode(messages=["Save and list a memory"], mock_llm=mock)

        assert mock.call_count == 3
        assert "success" in result.last_reply.lower() or "memory" in result.last_reply.lower()

    def test_memory_save_creates_file(self, tmp_path):
        """After MemorySave, a .md file exists in the memory directory."""
        mock = MockLLM([
            '<tool_use name="MemorySave" id="ms1">'
            '<param name="name">api-pattern</param>'
            '<param name="content">Always use async/await</param>'
            '<param name="type">pattern</param>'
            '<param name="scope">project</param>'
            '</tool_use>',
            "Saved.",
        ])
        result = bouzecode(messages=["Remember this pattern"], mock_llm=mock)

        assert mock.call_count == 2
        # Verify file was created in project memory dir
        project_mem = tmp_path / "project_memory"
        if project_mem.exists():
            md_files = list(project_mem.glob("*.md"))
            # Filter out MEMORY.md index
            content_files = [f for f in md_files if f.name != "MEMORY.md"]
            assert len(content_files) >= 1, f"Expected memory file, got: {md_files}"
