# [desc] A skill frontmatter is delimited by a line that is exactly `---`, never by a `---` substring in the body. [/desc]
"""Une skill mal délimitée est refusée bruyamment, jamais chargée amputée.

Le corps d'une skill contient couramment un tableau markdown, donc une ligne
`|------|`. Tant que le découpage se faisait sur la sous-chaîne `---`, une skill
dont le frontmatter n'était pas refermé se chargeait quand même, avec tout le haut
de son corps avalé dans le frontmatter et le reste pris pour le corps.
"""
from __future__ import annotations

from bouzecode.backend.tools.skill import load_skills

TABLE_SKILL_UNCLOSED = """\
---
name: tabled
description: une skill avec un tableau
Instructions importantes AVANT le tableau.

| Colonne | Sens |
|---------|------|
| a       | b    |

Instructions importantes APRES le tableau.
"""

TABLE_SKILL_CLOSED = """\
---
name: tabled
description: une skill avec un tableau
---
Instructions importantes AVANT le tableau.

| Colonne | Sens |
|---------|------|
| a       | b    |

Instructions importantes APRES le tableau.
"""


def _skill_dir(tmp_path, monkeypatch):
    """Point the loader at a throwaway project skills folder."""
    work = tmp_path / "work"
    (work / ".bouzecode" / "skills").mkdir(parents=True)
    monkeypatch.chdir(work)
    return work / ".bouzecode" / "skills"


def test_skill_with_table_and_unclosed_frontmatter_is_refused(tmp_path, monkeypatch, capsys):
    """Une skill dont le frontmatter n'est pas refermé n'est pas chargée à moitié : elle est refusée, avec un message."""
    directory = _skill_dir(tmp_path, monkeypatch)
    (directory / "tabled.md").write_text(TABLE_SKILL_UNCLOSED, encoding="utf-8")

    loaded = {s.name for s in load_skills(include_builtins=False)}

    assert "tabled" not in loaded
    assert "tabled.md" in capsys.readouterr().err


def test_skill_with_table_keeps_its_whole_body_when_frontmatter_is_closed(tmp_path, monkeypatch):
    """Un tableau markdown dans le corps ne coupe rien : le corps est conservé en entier."""
    directory = _skill_dir(tmp_path, monkeypatch)
    (directory / "tabled.md").write_text(TABLE_SKILL_CLOSED, encoding="utf-8")

    skill = next(s for s in load_skills(include_builtins=False) if s.name == "tabled")

    assert skill.description == "une skill avec un tableau"
    assert "AVANT le tableau" in skill.prompt
    assert "APRES le tableau" in skill.prompt


def test_closing_delimiter_glued_to_the_last_field_still_closes(tmp_path, monkeypatch):
    """La plupart des skills réelles collent le `---` de fermeture à la fin de la description : ça reste valide."""
    directory = _skill_dir(tmp_path, monkeypatch)
    (directory / "collee.md").write_text(
        '---\nname: collee\ndescription: "quand refactorer"---\n\n'
        "| Colonne | Sens |\n|---------|------|\n| a       | b    |\n\ncorps complet.",
        encoding="utf-8")

    skill = next(s for s in load_skills(include_builtins=False) if s.name == "collee")

    assert skill.description == '"quand refactorer"'
    assert "corps complet." in skill.prompt


def test_one_broken_skill_does_not_prevent_the_others_from_loading(tmp_path, monkeypatch):
    """Une skill cassée dans le dossier de l'utilisateur n'empêche pas les autres de se charger."""
    directory = _skill_dir(tmp_path, monkeypatch)
    (directory / "tabled.md").write_text(TABLE_SKILL_UNCLOSED, encoding="utf-8")
    (directory / "sane.md").write_text(
        "---\nname: sane\ndescription: ok\n---\ncorps intact", encoding="utf-8")

    loaded = {s.name for s in load_skills(include_builtins=False)}

    assert "sane" in loaded and "tabled" not in loaded
