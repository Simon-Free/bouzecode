"""Grep(path=<fichier réel>) ne doit chercher QUE dans ce fichier, jamais dans le scratch.

Bug 2026-10-12 : la boucle scratch de `_grep` ajoutait les hits de TOUS les fichiers
temp=True de la session, quel que soit `path`."""
from __future__ import annotations

from bouzecode.backend.tools.ops.grep_glob import _grep
from bouzecode.backend.tools.ops.scratch import resolve_scratch_path

NEEDLE = "AiguilleScope9c1d"


def _temp(tmp_path, nom, contenu):
    logical = str(tmp_path / "logique" / nom)
    real = resolve_scratch_path(logical)
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text(contenu, encoding="utf-8")
    return logical, real


def test_grep_real_file_ignores_scratch(tmp_path):
    reel = tmp_path / "reel" / "SKILL.md"
    reel.parent.mkdir()
    reel.write_text(f"titre\n{NEEDLE} dans le vrai\n", encoding="utf-8")
    _, real_tmp = _temp(tmp_path, "autre_notes.md", f"{NEEDLE} dans le scratch\n")

    out = _grep(NEEDLE, path=str(reel))

    assert "dans le vrai" in out
    assert "[scratch]" not in out and str(real_tmp) not in out, out


def test_grep_temp_logical_path_still_found(tmp_path):
    logical, real = _temp(tmp_path, "temp_found.txt", f"x\n{NEEDLE} temp\n")
    out = _grep(NEEDLE, path=logical)
    assert "[scratch]" in out and "temp" in out, out


def test_grep_dir_containing_temp_logical(tmp_path):
    logical, _ = _temp(tmp_path, "temp_in_dir.txt", f"{NEEDLE} sous dossier\n")
    (tmp_path / "logique").mkdir(exist_ok=True)
    out = _grep(NEEDLE, path=str(tmp_path / "logique"))
    assert "sous dossier" in out, out
