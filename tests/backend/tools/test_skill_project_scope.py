"""Skills stored in a loaded project must be found by SkillResearch and loadable by Skill.

Regression: a skill filed in <project>/.bouzecode/skills is implicitly scoped to
<project>. When the agent's cwd is the parent monorepo, the scope filter dropped it,
so LoadProjectConfig advertised skills that the skill search never found and Skill() could
not resolve. Loading a project now registers it as an extra scope anchor.
"""
from pathlib import Path

import pytest

from bouzecode.backend.core.paths import (
    add_extra_dir,
    clear_loaded_projects,
    get_extra_dirs,
    register_extra_dirs,
    register_loaded_project,
)
from bouzecode.backend.tools.skill.research import skill_research
from bouzecode.backend.tools.skill.tools import _skill_tool

PROBE_QUERY = {"query": "probe monorepo"}

SKILL_NAME = "zz-project-scope-probe"
SKILL_MARKER = "PROJECT SCOPE PROBE BODY"
SKILL_BODY = f"""---
name: {SKILL_NAME}
description: Probe skill stored inside a sub-project of a monorepo.
---

# Probe

{SKILL_MARKER}
"""


@pytest.fixture
def isolated_paths():
    """Restore the module-level extra dirs / loaded projects registries."""
    saved = get_extra_dirs()
    try:
        yield
    finally:
        register_extra_dirs(saved)
        clear_loaded_projects()


@pytest.fixture
def monorepo(tmp_path: Path) -> tuple[Path, Path]:
    """Return (monorepo_root, sub_project) with a skill stored in the sub-project."""
    root = tmp_path / "mono"
    project = root / "app"
    store = project / ".bouzecode" / "skills" / SKILL_NAME
    store.mkdir(parents=True)
    (store / "skill.md").write_text(SKILL_BODY, encoding="utf-8")
    return root, project


def _load_project(project: Path) -> None:
    """Do what LoadProjectConfig does for an equipped folder."""
    add_extra_dir(project / ".bouzecode")
    register_loaded_project(project)


def test_project_skill_absent_when_project_not_loaded(monorepo, isolated_paths, monkeypatch):
    root, _project = monorepo
    register_extra_dirs([])
    monkeypatch.chdir(root)

    assert SKILL_NAME not in skill_research(PROBE_QUERY, {})
    assert "not found" in _skill_tool({"name": SKILL_NAME}, {})


def test_skill_research_finds_project_skill_after_load(monorepo, isolated_paths, monkeypatch):
    root, project = monorepo
    register_extra_dirs([])
    _load_project(project)
    monkeypatch.chdir(root)

    assert SKILL_NAME in skill_research(PROBE_QUERY, {})


def test_skill_research_finds_project_skill_after_real_load_project_config(
        monorepo, isolated_paths, monkeypatch):
    """The real LoadProjectConfig, not a re-enactment: afterwards the skill is findable."""
    from bouzecode.backend.tools.ops.project_config import _load_project_config

    root, project = monorepo
    register_extra_dirs([])
    monkeypatch.chdir(root)
    assert SKILL_NAME not in skill_research(PROBE_QUERY, {})

    briefing = _load_project_config(str(project))

    assert SKILL_NAME not in briefing, "the briefing counts skills, it no longer lists them"
    assert "1 skill de projet disponible" in briefing
    assert SKILL_NAME in skill_research(PROBE_QUERY, {})


def test_skill_resolves_project_skill_after_load(monorepo, isolated_paths, monkeypatch):
    root, project = monorepo
    register_extra_dirs([])
    _load_project(project)
    monkeypatch.chdir(root)

    rendered = _skill_tool({"name": SKILL_NAME}, {})

    assert "not found" not in rendered
    assert SKILL_MARKER in rendered
