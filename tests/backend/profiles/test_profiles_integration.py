# [desc] Tests profile field parsing in AgentDefinition and profile resolution in SubAgentManager.
# <tool_use name="FinalAnswer" id="1"><param name="answer">Tests profile field parsing in AgentDefinition and profile resolution in SubAgentManager.</param></tool_use> [/desc]
"""Tests for profile resolution in multi_agent system."""
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bouzecode.backend.profiles import AgentProfile, merge_profiles, load_profiles_from_dir
from bouzecode.backend.multi_agent.definitions import AgentDefinition, _parse_agent_md


class TestAgentDefinitionProfiles:
    """Test that AgentDefinition supports the profiles field."""

    def test_agent_definition_has_profiles_field(self):
        """AgentDefinition has a profiles list field defaulting to empty."""
        ad = AgentDefinition(name="test")
        assert ad.profiles == []

    def test_agent_definition_with_profiles(self):
        """AgentDefinition accepts profiles in constructor."""
        ad = AgentDefinition(name="test", profiles=["analyst", "secure"])
        assert ad.profiles == ["analyst", "secure"]

    def test_parse_agent_md_with_profiles(self, tmp_path):
        """Parsing an agent .md file with profiles frontmatter extracts them."""
        md_content = (
            "---\n"
            "description: Test agent\n"
            "profiles:\n"
            "  - analyst\n"
            "  - secure\n"
            "tools:\n"
            "  - Read\n"
            "---\n"
            "You are a test agent.\n"
        )
        md_file = tmp_path / "test-agent.md"
        md_file.write_text(md_content)
        ad = _parse_agent_md(md_file)
        assert ad.name == "test-agent"
        assert ad.profiles == ["analyst", "secure"]
        assert ad.tools == ["Read"]
        assert "test agent" in ad.system_prompt


class TestManagerProfileResolution:
    """Test that SubAgentManager resolves profiles at spawn time."""

    def test_resolve_profiles_from_dir(self, tmp_path):
        """_resolve_profiles loads and merges profiles from directories."""
        from bouzecode.backend.multi_agent.manager import SubAgentManager

        # Create profile files
        profiles_dir = tmp_path / ".bouzecode" / "profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "fast.yaml").write_text(
            "name: fast\nskills:\n  - run-tests\ntools:\n  - Bash\nhooks: []\nmodel: gpt-4-mini\nsystem_prompt_extra: Be fast.\n"
        )
        (profiles_dir / "safe.yaml").write_text(
            "name: safe\nskills:\n  - troubleshooting\ntools:\n  - Read\nhooks:\n  - enforcement\nmodel: \"\"\nsystem_prompt_extra: Be safe.\n"
        )

        manager = SubAgentManager()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            resolved = manager._resolve_profiles(["fast", "safe"])
        finally:
            os.chdir(old_cwd)

        assert resolved is not None
        assert resolved.skills == ["run-tests", "troubleshooting"]
        assert resolved.tools == ["Bash", "Read"]
        assert resolved.hooks == ["enforcement"]
        assert resolved.model == "gpt-4-mini"  # last non-empty = fast (safe is empty)
        assert "Be fast." in resolved.system_prompt_extra
        assert "Be safe." in resolved.system_prompt_extra

    def test_resolve_profiles_unknown_names_returns_none(self, tmp_path):
        """_resolve_profiles returns None when no profiles match."""
        from bouzecode.backend.multi_agent.manager import SubAgentManager

        manager = SubAgentManager()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            resolved = manager._resolve_profiles(["nonexistent"])
        finally:
            os.chdir(old_cwd)

        assert resolved is None
