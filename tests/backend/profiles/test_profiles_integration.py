# [desc] Tests AgentProfile merge/resolution in the SubAgentManager. [/desc]
"""Tests for profile resolution in multi_agent system."""
import os


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
