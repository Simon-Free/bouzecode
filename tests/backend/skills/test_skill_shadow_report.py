# [desc] A shadowed skill is announced on stderr at load time instead of being dropped in silence. [/desc]
"""Shadowing must be loud.

Two same-named skills used to be arbitrated by storage priority with no signal at all:
you thought you were using your project skill, you were using the user one, and nothing
said so. Every shadowing now costs one stderr line — zero context tokens, and the operator
finally sees it.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.tools.skill import load_skills


def _file_skill(folder, name: str, body: str) -> None:
    target = folder / ".bouzecode" / "skills" / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "skill.md").write_text(
        f"---\nname: {name}\ndescription: {body}\n---\n\n{body}\n", encoding="utf-8")


@pytest.fixture()
def nested_projects(tmp_path):
    """An outer project and an inner one, both defining `shadow-probe-skill`."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    _file_skill(outer, "shadow-probe-skill", "outer version")
    _file_skill(inner, "shadow-probe-skill", "inner version")
    return outer, inner


def test_loading_announces_which_skill_shadowed_which(nested_projects, monkeypatch, capsys):
    """Loading from the inner project names the loser, the winner, and both paths."""
    outer, inner = nested_projects
    monkeypatch.chdir(inner)

    load_skills()

    reported = capsys.readouterr().err
    assert "shadow-probe-skill" in reported
    assert "masquée par" in reported
    assert str(outer / ".bouzecode") in reported
    assert str(inner / ".bouzecode") in reported


def test_the_same_shadowing_is_not_repeated_on_every_load(nested_projects, monkeypatch, capsys):
    """Skills reload several times per tool call: a warning repeated 40× is unread."""
    _, inner = nested_projects
    monkeypatch.chdir(inner)

    load_skills()
    capsys.readouterr()
    load_skills()

    assert "shadow-probe-skill" not in capsys.readouterr().err


def test_a_skill_with_no_namesake_is_never_reported(tmp_path, monkeypatch, capsys):
    """No collision, no noise."""
    project = tmp_path / "solo"
    project.mkdir()
    _file_skill(project, "lonely-probe-skill", "sole version")
    monkeypatch.chdir(project)

    load_skills()

    assert "lonely-probe-skill" not in capsys.readouterr().err
