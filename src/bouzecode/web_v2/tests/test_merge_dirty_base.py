# [desc] Le merge d'un enfant n'est plus otage d'un arbre develop sale (stash → merge → restore). [/desc]
"""Bug structurel « les merges automatiques ne se déclenchent pas » : `base` (develop) est
checkout dans l'arbre PARTAGÉ (serveur + agents). git ne peut pas avancer une branche checkout
dont l'arbre porte des modifs non commitées → on REFUSAIT, donc le moindre artefact orphelin
bloquait TOUS les merges. Fix : stash (tracked+untracked) → merge → restore. Aucun travail perdu.

Vrai dépôt git en tmp, aucun fake."""
import subprocess
from pathlib import Path

from bouzecode.web_v2.services.work import worktrees


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8")


def _repo(tmp: Path):
    # isole WORKTREES_DIR dans le tmp du test (sinon provision écrit sous le VRAI
    # ~/.bouzecode/worktrees/ → collision de slug entre tests parallèles).
    worktrees.WORKTREES_DIR = tmp / "wts"
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    (repo / "feature.txt").write_text("base\n")
    (repo / "keep.txt").write_text("humain v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return repo, base


def _child_delivers(repo, base):
    """Un enfant modifie feature.txt dans SON worktree et commit sur sa branche agent."""
    meta = worktrees.provision(str(repo), "tk-dirty", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "feature.txt").write_text("livraison enfant\n")
    worktrees.harvest(meta, "travail enfant")
    return meta


def test_dirty_tracked_base_still_merges_and_restores(tmp_path):
    repo, base = _repo(tmp_path)
    meta = _child_delivers(repo, base)
    # arbre principal SALE (tracked) sur un fichier SANS rapport avec le merge — l'ancien code
    # refusait ici (« merge manuel requis »).
    (repo / "keep.txt").write_text("humain WIP non commité\n")
    assert worktrees._tracked_dirty(str(repo))

    res = worktrees.integrate(meta)

    assert res["ok"] and res["state"] == "integrated", res
    # (a) le travail de l'enfant est bien dans develop
    assert (repo / "feature.txt").read_text() == "livraison enfant\n"
    # (b) le WIP non commité de l'humain est RESTAURÉ (aucune perte)
    assert (repo / "keep.txt").read_text() == "humain WIP non commité\n"
    assert worktrees._tracked_dirty(str(repo))
    # (c) un vrai commit de merge existe
    assert _git(repo, "rev-parse", "HEAD^2").returncode == 0


def test_untracked_orphan_in_base_does_not_block_merge(tmp_path):
    repo, base = _repo(tmp_path)
    meta = _child_delivers(repo, base)
    # artefact orphelin UNTRACKED (ex : un test laissé par la flotte)
    (repo / "orphan_test.py").write_text("# laissé par un agent\n")
    assert worktrees._has_untracked(str(repo))

    res = worktrees.integrate(meta)

    assert res["ok"] and res["state"] == "integrated", res
    assert (repo / "feature.txt").read_text() == "livraison enfant\n"
    # l'orphelin untracked est restauré, toujours présent
    assert (repo / "orphan_test.py").exists()


def test_clean_base_merges_as_before(tmp_path):
    repo, base = _repo(tmp_path)
    meta = _child_delivers(repo, base)  # arbre principal PROPRE

    res = worktrees.integrate(meta)

    assert res["ok"] and res["state"] == "integrated", res
    assert (repo / "feature.txt").read_text() == "livraison enfant\n"
    assert not worktrees._tracked_dirty(str(repo))
