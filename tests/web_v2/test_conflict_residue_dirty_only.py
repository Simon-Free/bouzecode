# [desc] `_conflict_residue` ne grep QUE les fichiers sales (modifiés depuis HEAD ou non
# suivis) : sur tout l'arbre, la lecture à froid coûtait 12 à 15 s par harvest/integrate.
# Vrais dépôts git dans tmp_path ; les appels git sont comptés par GIT_TRACE. [/desc]
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import worktrees
from tests.git_modeles import develop_un_commit

_CONFLIT = "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> other\n"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _commit_all(cwd, msg):
    _git(cwd, "add", "-A")
    _git(cwd, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", msg)


@pytest.fixture
def repo(tmp_path, depot_modele) -> Path:
    """`develop` portant `doc.md` avec un marqueur COMMITTÉ (doc sur les conflits)."""
    racine = depot_modele(tmp_path / "repo", develop_un_commit)
    (racine / "doc.md").write_text("Exemple :\n" + _CONFLIT, encoding="utf-8")
    _commit_all(racine, "doc")
    return racine


@pytest.fixture
def trace_git(tmp_path, monkeypatch) -> Path:
    """Journal GIT_TRACE des commandes git lancées par les sous-process."""
    journal = tmp_path / "git_trace.log"
    monkeypatch.setenv("GIT_TRACE", str(journal))
    return journal


def _greps_lances(journal: Path) -> list[str]:
    if not journal.exists():
        return []
    return [ln for ln in journal.read_text(encoding="utf-8", errors="replace").splitlines()
            if "built-in: git" in ln and " grep " in ln]


def test_marqueur_committe_dans_fichier_intact_ne_bloque_pas(repo):
    assert worktrees._conflict_residue(str(repo)) == []
    assert worktrees.blocage_recolte(str(repo)) is None


def test_marqueur_introduit_dans_fichier_modifie_bloque(repo):
    (repo / "f.txt").write_text("A\n" + _CONFLIT, encoding="utf-8")

    assert worktrees._conflict_residue(str(repo)) == ["f.txt"]
    assert worktrees.blocage_recolte(str(repo))["fichiers"] == ["f.txt"]


def test_marqueur_dans_fichier_indexe_bloque(repo):
    (repo / "f.txt").write_text("A\n" + _CONFLIT, encoding="utf-8")
    _git(repo, "add", "f.txt")

    assert worktrees._conflict_residue(str(repo)) == ["f.txt"]


def test_marqueur_dans_fichier_renomme_bloque(repo):
    _git(repo, "mv", "f.txt", "g.txt")
    (repo / "g.txt").write_text("A\n" + _CONFLIT, encoding="utf-8")
    _git(repo, "add", "g.txt")

    assert worktrees._conflict_residue(str(repo)) == ["g.txt"]


def test_marqueur_dans_nouveau_fichier_non_suivi_bloque(repo):
    (repo / "sous dossier").mkdir()
    (repo / "sous dossier" / "neuf[1].py").write_text(_CONFLIT, encoding="utf-8")

    assert worktrees._conflict_residue(str(repo)) == ["sous dossier/neuf[1].py"]
    assert worktrees.blocage_recolte(str(repo))["fichiers"] == ["sous dossier/neuf[1].py"]


def test_fichier_ignore_n_est_pas_lu(repo):
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _commit_all(repo, "ignore")
    (repo / "trace.log").write_text(_CONFLIT, encoding="utf-8")

    assert worktrees._conflict_residue(str(repo)) == []


def test_etat_uu_est_detecte(repo):
    _git(repo, "checkout", "-qb", "autre")
    (repo / "f.txt").write_text("B\n", encoding="utf-8")
    _commit_all(repo, "B")
    _git(repo, "checkout", "-q", "develop")
    (repo / "f.txt").write_text("C\n", encoding="utf-8")
    _commit_all(repo, "C")
    assert _git(repo, "merge", "autre").returncode != 0

    assert worktrees._conflict_residue(str(repo)) == ["f.txt"]


def test_arbre_propre_ne_lance_aucun_grep(repo, trace_git):
    assert worktrees._conflict_residue(str(repo)) == []
    assert _greps_lances(trace_git) == []


def test_arbre_sale_ne_grep_que_les_fichiers_sales(repo, trace_git):
    (repo / "f.txt").write_text("A\nB\n", encoding="utf-8")

    assert worktrees._conflict_residue(str(repo)) == []
    greps = _greps_lances(trace_git)
    assert len(greps) == 1
    assert greps[0].rstrip().endswith("-- f.txt")


def test_beaucoup_de_fichiers_sales_sont_lus_par_lots(repo, trace_git):
    noms = [f"fichier_{i:04d}_{'x' * 40}.txt" for i in range(400)]
    for nom in noms:
        (repo / nom).write_text("rien\n", encoding="utf-8")
    (repo / noms[-1]).write_text(_CONFLIT, encoding="utf-8")

    assert worktrees._conflict_residue(str(repo)) == [noms[-1]]
    assert len(_greps_lances(trace_git)) > 1


def test_lots_respectent_le_plafond():
    lots = worktrees._lots(["a" * 9, "b" * 9, "c" * 9], plafond=20)
    assert lots == [["a" * 9, "b" * 9], ["c" * 9]]
    assert worktrees._lots([]) == []
