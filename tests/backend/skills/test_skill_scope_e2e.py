# [desc] Conversation tests: a project-scoped skill is served to an agent working in that project and is invisible from another one. [/desc]
"""Skill SCOPE observed through real bouzecode() conversations.

The user story: "the skills used only by the bouzecode of demo_app". Two
sibling projects each file a `deploy` skill under their own `.bouzecode/skills/`. An
agent working in one must be served ITS deploy, never the neighbour's — and a project
skill must not follow the agent into an unrelated tree.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
# Conversations close on PLAIN TEXT here. The usual `f"done.\n{METH}"` close is broken at
# HEAD (a meta-only batch no longer ends the session, so the MockLLM queue is exhausted);
# another agent owns that fix. Plain text is a legitimate close and dodges nothing.
CLOSE = "C'est fait."


def _write_project_skill(project_root, name: str, body: str, scope_line: str = "") -> None:
    """File a skill under <project_root>/.bouzecode/skills/<name>/skill.md."""
    folder = project_root / ".bouzecode" / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "skill.md").write_text(
        f"---\nname: {name}\ndescription: deploy for {project_root.name}\n{scope_line}---\n\n{body}\n",
        encoding="utf-8",
    )


def _invoke_skill_from(cwd, monkeypatch, name: str) -> str:
    """Run a conversation whose working directory is `cwd`; return the Skill tool result."""
    monkeypatch.chdir(cwd)
    call = f'<tool_use name="Skill" id="sk1"><param name="name">{name}</param></tool_use>'
    mock = MockLLM([f"{METH}\n{call}", CLOSE])
    result = bouzecode([f"use {name}"], mock_llm=mock)
    results = [m for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "Skill"]
    assert results, "no Skill tool result in transcript"
    return results[0]["content"]


@pytest.fixture()
def two_projects(tmp_path):
    """Two sibling projects, each with its own `deploy` skill."""
    application = tmp_path / "demo_app"
    ingestion = tmp_path / "demo_ingestion"
    _write_project_skill(application, "deploy", "Deploy APPLICATION with az webapp.")
    _write_project_skill(ingestion, "deploy", "Deploy INGESTION with batch jobs.")
    return application, ingestion


def test_agent_is_served_the_deploy_skill_of_the_project_it_works_in(two_projects, monkeypatch):
    """Working in demo_app, Skill(deploy) returns the APPLICATION body."""
    application, _ = two_projects
    out = _invoke_skill_from(application, monkeypatch, "deploy")
    assert "Deploy APPLICATION" in out
    assert "Deploy INGESTION" not in out


def test_the_neighbouring_project_skill_is_invisible(two_projects, monkeypatch):
    """The same call from demo_ingestion returns the INGESTION body, not its neighbour's."""
    _, ingestion = two_projects
    out = _invoke_skill_from(ingestion, monkeypatch, "deploy")
    assert "Deploy INGESTION" in out
    assert "Deploy APPLICATION" not in out


def test_a_project_skill_does_not_follow_the_agent_into_another_tree(tmp_path, monkeypatch):
    """A skill filed in one project is not offered to an agent working elsewhere."""
    project = tmp_path / "some_project"
    _write_project_skill(project, "project-only-skill", "Secret project knowledge.")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    out = _invoke_skill_from(elsewhere, monkeypatch, "project-only-skill")
    assert "not found" in out
    assert "Secret project knowledge" not in out


def test_a_skill_scoped_to_a_parent_directory_covers_its_subprojects(tmp_path, monkeypatch):
    """A monorepo-level skill is visible from a sub-project of that monorepo."""
    monorepo = tmp_path / "monorepo"
    subproject = monorepo / "packages" / "web"
    subproject.mkdir(parents=True)
    _write_project_skill(monorepo, "house-rules", "Monorepo house rules.")

    out = _invoke_skill_from(subproject, monkeypatch, "house-rules")
    assert "Monorepo house rules" in out


# ── two scopes, one name: the narrower wins and the loser is NAMED ───────────

@pytest.fixture()
def monorepo_and_subproject(tmp_path):
    """A monorepo and one of its packages, both filing a skill called `deploy`."""
    monorepo = tmp_path / "monorepo"
    subproject = monorepo / "packages" / "web"
    subproject.mkdir(parents=True)
    _write_project_skill(monorepo, "deploy", "Deploy the WHOLE monorepo.")
    _write_project_skill(subproject, "deploy", "Deploy only the WEB package.")
    return monorepo, subproject


def test_the_narrower_scope_wins_over_the_enclosing_one(monorepo_and_subproject, monkeypatch):
    """From packages/web, `deploy` is the package's, not the monorepo's."""
    _, subproject = monorepo_and_subproject
    out = _invoke_skill_from(subproject, monkeypatch, "deploy")
    assert "Deploy only the WEB package" in out
    assert "Deploy the WHOLE monorepo" not in out


def test_the_qualified_name_reaches_the_same_skill(monorepo_and_subproject, monkeypatch):
    """A collision qualifies the winner's name, and `web:deploy` resolves to it."""
    _, subproject = monorepo_and_subproject
    out = _invoke_skill_from(subproject, monkeypatch, "web:deploy")
    assert "Deploy only the WEB package" in out


def test_skill_list_names_the_shadowed_skill_and_both_paths(monorepo_and_subproject, monkeypatch):
    """SkillList reports the shadowing instead of resolving it in silence."""
    monorepo, subproject = monorepo_and_subproject
    monkeypatch.chdir(subproject)
    call = '<tool_use name="SkillList" id="sl1"></tool_use>'
    mock = MockLLM([f"{METH}\n{call}", CLOSE])
    result = bouzecode(["quelles skills ai-je ?"], mock_llm=mock)
    listing = next(m["content"] for m in result.messages
                   if m.get("role") == "tool" and m.get("name") == "SkillList")

    assert "## Masquées" in listing
    assert str(monorepo / ".bouzecode") in listing      # the shadowed one, by path
    assert str(subproject / ".bouzecode") in listing    # and the one that shadows it
    assert "web:deploy" in listing                      # the winner is qualified
