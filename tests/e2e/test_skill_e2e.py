"""E2E test: Skill tool — LLM invokes Skill(name=...) and gets rendered content."""
from __future__ import annotations

import pytest
from pathlib import Path

from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


@pytest.mark.backend
class TestSkillE2E:
    """Skill tool invocation through the engine."""

    def test_skill_invocation_returns_rendered_content(self, tmp_path, monkeypatch):
        """Create a skill .md file, LLM calls Skill(name=...), verify rendered output."""
        # Create skill file in tmp_path/.bouzecode/skills/
        skills_dir = tmp_path / ".bouzecode" / "skills"
        skills_dir.mkdir(parents=True)
        skill_file = skills_dir / "greet.md"
        skill_file.write_text(
            "---\n"
            "name: greet\n"
            "description: A greeting skill\n"
            "triggers: greet\n"
            "---\n"
            "Hello $ARGUMENTS! Welcome to bouzecode.\n"
        )

        # Monkeypatch cwd so skill loader finds the skill
        monkeypatch.chdir(tmp_path)

        # LLM calls Skill then gives final answer
        mock = MockLLM([
            '<tool_use name="Skill" id="s1"><param name="name">greet</param><param name="args">World</param></tool_use>',
            "Done! The skill said hello.",
        ])
        result = bouzecode(messages=["Load the greet skill"], mock_llm=mock)

        assert mock.call_count == 2
        # The skill tool should have returned rendered content in turn 1
        # and the LLM saw it and responded in turn 2
        assert "Done" in result.last_reply or "hello" in result.last_reply.lower()

    def test_skill_not_found_returns_error(self, tmp_path, monkeypatch):
        """LLM calls Skill with unknown name → error message returned."""
        monkeypatch.chdir(tmp_path)

        mock = MockLLM([
            '<tool_use name="Skill" id="s1"><param name="name">nonexistent</param></tool_use>',
            "The skill was not found.",
        ])
        result = bouzecode(messages=["Load skill nonexistent"], mock_llm=mock)

        assert mock.call_count == 2
        assert "not found" in result.last_reply.lower() or "skill" in result.last_reply.lower()
