# [desc] Tests for LoadProjectConfig tool: project detection, skills, MCP, plugins, hooks, and registration [/desc]
"""Tests for LoadProjectConfig tool."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bouzecode.backend.core.paths as paths
from bouzecode.backend.tools.ops.project_config import _load_project_config, _extract_skill_description


@pytest.fixture(autouse=True)
def _reset_extra_dirs():
    """Reset extra dirs between tests."""
    paths._extra_dirs = []
    yield
    paths._extra_dirs = []


def test_no_bouzecode_dir(tmp_path):
    result = _load_project_config(str(tmp_path))
    assert "Error" in result
    assert ".bouzecode/" in result


def test_empty_bouzecode_dir(tmp_path):
    (tmp_path / ".bouzecode").mkdir()
    result = _load_project_config(str(tmp_path))
    assert "Registered" in result
    assert "(empty" in result
    assert tmp_path.resolve() / ".bouzecode" in paths.get_extra_dirs()


def test_with_skills(tmp_path):
    skills_dir = tmp_path / ".bouzecode" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "deploy.md").write_text(
        "---\ndescription: Deploy to production\n---\nDeploy steps...",
        encoding="utf-8",
    )
    (skills_dir / "test.md").write_text("No frontmatter", encoding="utf-8")

    result = _load_project_config(str(tmp_path))
    assert "Skills (2):" in result
    assert "deploy — Deploy to production" in result
    assert "test" in result


def test_with_mcp_config(tmp_path):
    bz = tmp_path / ".bouzecode"
    bz.mkdir()
    mcp_data = {"mcpServers": {"filesystem": {"command": "node"}, "github": {"command": "gh"}}}
    (bz / "mcp.json").write_text(json.dumps(mcp_data), encoding="utf-8")

    result = _load_project_config(str(tmp_path))
    assert "MCP servers (2):" in result
    assert "filesystem" in result
    assert "github" in result


def test_with_plugins(tmp_path):
    plugins_dir = tmp_path / ".bouzecode" / "plugins"
    (plugins_dir / "my_plugin").mkdir(parents=True)
    (plugins_dir / "other_plugin").mkdir(parents=True)

    result = _load_project_config(str(tmp_path))
    assert "Plugins (2):" in result
    assert "my_plugin" in result
    assert "other_plugin" in result


def test_with_hooks(tmp_path):
    hooks_dir = tmp_path / ".bouzecode" / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "pre_commit.py").write_text("# hook", encoding="utf-8")

    result = _load_project_config(str(tmp_path))
    assert "Hooks (1):" in result
    assert "pre_commit.py" in result


def test_cumulative_calls(tmp_path):
    proj1 = tmp_path / "proj1"
    proj2 = tmp_path / "proj2"
    (proj1 / ".bouzecode" / "skills").mkdir(parents=True)
    (proj2 / ".bouzecode" / "skills").mkdir(parents=True)

    result1 = _load_project_config(str(proj1))
    assert "Registered" in result1

    result2 = _load_project_config(str(proj2))
    assert "Registered" in result2

    dirs = paths.get_extra_dirs()
    assert len(dirs) == 2
    assert (proj1.resolve() / ".bouzecode") in dirs
    assert (proj2.resolve() / ".bouzecode") in dirs


def test_already_registered(tmp_path):
    (tmp_path / ".bouzecode").mkdir()
    _load_project_config(str(tmp_path))
    result = _load_project_config(str(tmp_path))
    assert "Already registered" in result
    assert len(paths.get_extra_dirs()) == 1


def test_extract_skill_description(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text('---\ndescription: "My cool skill"\n---\nContent', encoding="utf-8")
    assert _extract_skill_description(f) == "My cool skill"


def test_extract_skill_description_no_frontmatter(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text("Just content", encoding="utf-8")
    assert _extract_skill_description(f) == ""


def test_malformed_mcp_json(tmp_path):
    bz = tmp_path / ".bouzecode"
    bz.mkdir()
    (bz / "mcp.json").write_text("not json", encoding="utf-8")

    result = _load_project_config(str(tmp_path))
    assert "parse error" in result
