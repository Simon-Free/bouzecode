# [desc] Estampille de commit sans lancer git : read_head_short rend exactement `git rev-parse --short HEAD` sur de vrais dépôts (branche, ref packée, HEAD détaché, worktree lié). [/desc]
"""L'estampille `bouzecode_commit` était un `git rev-parse --short HEAD` à chaque run : ~165 ms
de spawn, 92 % du temps d'un test e2e. Elle est désormais lue dans `.git` ; ces tests la
comparent à la sortie RÉELLE de git sur des dépôts créés pour l'occasion."""
from __future__ import annotations

import subprocess

import pytest

from bouzecode.backend.agent.loop import _get_bouzecode_commit
from bouzecode.backend.core import code_version as cv


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, timeout=30).stdout.strip()


def _short_attendu(repo) -> str:
    return _git(repo, "rev-parse", "--short", "HEAD")


@pytest.fixture
def depot(tmp_path):
    repo = tmp_path / "depot"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    for i in range(2):
        (repo / "f.txt").write_text(f"v{i}\n")
        _git(repo, "add", "f.txt")
        _git(repo, "commit", "-q", "-m", f"c{i}")
    return repo


def test_branche_normale(depot):
    assert cv.read_head_short(str(depot)) == _short_attendu(depot)


def test_ref_packee_et_objets_en_pack(depot):
    _git(depot, "gc", "-q")  # refs -> packed-refs, objets -> pack + .idx
    assert not (depot / ".git" / "refs" / "heads" / "main").exists()
    assert cv.read_head_short(str(depot)) == _short_attendu(depot)


def test_head_detache(depot):
    _git(depot, "checkout", "-q", "--detach", "HEAD~1")
    assert cv.read_head_short(str(depot)) == _short_attendu(depot)


def test_worktree_lie(depot, tmp_path):
    wt = tmp_path / "wt"
    _git(depot, "worktree", "add", "-q", "-b", "agent/x", str(wt), "HEAD~1")
    assert (wt / ".git").is_file(), "un worktree lié porte un FICHIER .git"
    assert cv.read_head_short(str(wt)) == _short_attendu(wt)
    _git(depot, "gc", "-q")  # la ref de branche du worktree passe dans packed-refs commun
    assert cv.read_head_short(str(wt)) == _short_attendu(wt)


def test_hors_depot_rend_vide(tmp_path):
    assert cv.read_head_short(str(tmp_path)) == ""
    assert cv.read_head_short("") == ""


@pytest.mark.parametrize("objets, longueur", [(0, 7), (1, 7), (2**13 - 1, 7), (2**13, 7),
                                              (2**14, 8), (49494, 8), (2**16, 9)])
def test_longueur_d_abrege_de_git(objets, longueur):
    """Formule de git (core.abbrev auto) : ceil(bits(n) / 2), au moins 7."""
    assert cv._abbrev_len(objets) == longueur


def test_estampille_de_la_boucle_egale_git_sur_le_depot_bouzecode():
    """Le vrai dépôt, gros assez pour que git abrège au-delà de 7 caractères."""
    if not cv.REPO_ROOT:
        pytest.skip("paquet installé hors dépôt git")
    assert _get_bouzecode_commit() == _short_attendu(cv.REPO_ROOT)
