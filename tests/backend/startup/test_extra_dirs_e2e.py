# [desc] End-to-end tests verifying extra dirs inject skills and MCP tools into conversations [/desc]
"""End-to-end tests verifying extra dirs inject tools/skills into real conversations."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import bouzecode.backend.core.paths as _paths


@pytest.fixture(autouse=True)
def reset_extra_dirs():
    _paths._extra_dirs = []
    yield
    _paths._extra_dirs = []


class TestExtraDirSkillsE2E:
    """Verify extra-dir skills are discoverable (prompt V2: via the skill loader
    / SkillList, no longer listed in the system prompt)."""

    def test_extra_dir_skill_appears_in_context(self, tmp_path, monkeypatch):
        """A skill in an extra dir is returned by the skill loader."""
        from bouzecode.backend.tools.skill import loader as _loader

        # Create extra dir with a skill
        extra = tmp_path / "extra"
        skills_dir = extra / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "custom_deploy.md").write_text(
            "---\nname: custom-deploy\ndescription: Deploy to custom env\n---\nDeploy steps here\n",
            encoding="utf-8",
        )
        _paths.register_extra_dirs([str(extra)])

        # Patch other paths to empty so only extra dir matters
        monkeypatch.setattr(_loader, "_BUILTIN_SKILLS", [])
        original_get = _loader._get_skill_paths

        # Only keep the extra dir from the paths
        def patched_paths():
            paths = original_get()
            # filter to only extra-based ones (paths are tuples (Path, source))
            return [(p, s) for p, s in paths if str(extra) in str(p)]

        monkeypatch.setattr(_loader, "_get_skill_paths", patched_paths)

        names = {s.name: s.description for s in _loader.load_skills()}
        assert "custom-deploy" in names
        assert "Deploy to custom env" in names["custom-deploy"]

    def test_extra_dir_skill_overrides_project(self, tmp_path, monkeypatch):
        """Extra dir skill with same name overrides project skill."""
        from bouzecode.backend.tools.skill import loader as _loader

        # Project skill
        proj_skills = tmp_path / "project" / "skills"
        proj_skills.mkdir(parents=True)
        (proj_skills / "deploy.md").write_text(
            "---\nname: deploy\ndescription: Project deploy\n---\nproject\n",
            encoding="utf-8",
        )

        # Extra dir skill (same name)
        extra = tmp_path / "extra"
        extra_skills = extra / "skills"
        extra_skills.mkdir(parents=True)
        (extra_skills / "deploy.md").write_text(
            "---\nname: deploy\ndescription: Extra deploy WINS\n---\nextra\n",
            encoding="utf-8",
        )
        _paths.register_extra_dirs([str(extra)])

        monkeypatch.setattr(_loader, "_BUILTIN_SKILLS", [])
        monkeypatch.setattr(_loader, "_get_skill_paths", lambda: [
            (extra_skills, "extra"),   # extra (highest)
            (proj_skills, "project"),  # project
        ])

        from bouzecode.backend.tools.skill.loader import load_skills
        skills = load_skills(include_builtins=False)
        deploy = next(s for s in skills if s.name == "deploy")
        assert deploy.description == "Extra deploy WINS"


# TestExtraDirMcpE2E and TestExtraDirPluginsE2E removed: the bouzecode.backend.mcp
# and bouzecode.backend.plugin modules were deleted, so extra-dir MCP-server and
# plugin discovery no longer exist.
