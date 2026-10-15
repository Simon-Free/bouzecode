# [desc] A skill whose scope: names a directory absent from this machine is announced on stderr instead of vanishing silently. [/desc]
"""A `scope:` pointing nowhere must be loud.

Typically an absolute path written on another workstation: `covers()` never matches, the
skill disappears from SkillResearch, and nothing said why.
"""
from bouzecode.backend.tools.skill import load_skills


def _file_scoped_skill(project, name, scope):
    target = project / ".bouzecode" / "skills" / name
    target.mkdir(parents=True)
    (target / "skill.md").write_text(
        f"---\nname: {name}\ndescription: scoped\nscope: {scope}\n---\n\nbody\n",
        encoding="utf-8")


def test_a_missing_absolute_scope_is_reported_once(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    missing = tmp_path / "autre_poste" / "demo"
    _file_scoped_skill(project, "scope-missing-probe", missing)
    monkeypatch.chdir(project)

    names = {s.name for s in load_skills()}
    first = capsys.readouterr().err
    load_skills()
    second = capsys.readouterr().err

    assert "scope-missing-probe" not in names
    assert "scope-missing-probe" in first
    assert str(missing) in first
    assert "scope-missing-probe" not in second


def test_an_existing_scope_is_not_reported(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    _file_scoped_skill(project, "scope-present-probe", project)
    monkeypatch.chdir(project)

    names = {s.name for s in load_skills()}

    assert "scope-present-probe" in names
    assert "scope-present-probe" not in capsys.readouterr().err
