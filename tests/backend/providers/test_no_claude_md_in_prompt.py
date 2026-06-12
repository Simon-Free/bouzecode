# [desc] Regression test ensuring CLAUDE.md file content never pollutes the system prompt sent to LLMs
# 
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Regression test ensuring CLAUDE.md file content never pollutes the system prompt sent to LLMs</param></tool_use> [/desc]
"""Regression test: CLAUDE.md files (global or project) must NOT pollute the
system prompt sent to any LLM. They are for Claude Code, not bouzecode."""
import pytest
from unittest.mock import patch
from pathlib import Path

from bouzecode.backend.core.context import build_system_prompt_parts


class TestClaudeMdNotInPrompt:
    """CLAUDE.md content should never appear in the system prompt."""

    def test_stable_prompt_does_not_contain_claude_md_header(self):
        """The '[Global CLAUDE.md]' or '[Project CLAUDE.md' markers must be absent."""
        stable, _ = build_system_prompt_parts({})
        assert "[Global CLAUDE.md]" not in stable, (
            "Global CLAUDE.md content is leaking into the system prompt"
        )
        assert "[Project CLAUDE.md" not in stable, (
            "Project CLAUDE.md content is leaking into the system prompt"
        )

    def test_stable_prompt_does_not_contain_claude_md_section(self):
        """The '# Memory / CLAUDE.md' section header must be absent."""
        stable, _ = build_system_prompt_parts({})
        assert "# Memory / CLAUDE.md" not in stable, (
            "CLAUDE.md section header is present in system prompt"
        )
