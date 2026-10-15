"""Résolution de la branche de base d'un worktree, sur de vrais dépôts git jetables.

Régression : `Environment(action='worktree')` rendait « fatal: invalid reference: main » sur un
dépôt qui ne possède aucune branche `main` locale (dépôt sur `master`, ou dépôt sans commit).
"""
import subprocess
from pathlib import Path

from bouzecode.web_v2.services.work import worktrees


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _repo(tmp: Path, name: str, branch: str) -> Path:
    """Dépôt avec un commit, dont la branche sortie s'appelle `branch`."""
    repo = tmp / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    (repo / "a.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    _git(repo, "branch", "-M", branch)
    return repo


def test_base_est_master_quand_origin_head_annonce_main(tmp_path):
    """origin/HEAD = main mais aucune branche main locale : la base doit rester `master`."""
    worktrees.WORKTREES_DIR = tmp_path / "wts"
    repo = _repo(tmp_path, "sur-master", "master")
    # origin/HEAD annonce une branche qui n'existe PAS localement (cas des dépôts clonés
    # dont le HEAD distant est main alors que le travail se fait sur master).
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    assert worktrees.default_branch(str(repo)) == "master"

    meta = worktrees.provision(str(repo), "tk-master", with_venv=False)
    assert meta["ok"], meta
    assert meta["base"] == "master"


def test_develop_prioritaire_sur_master(tmp_path):
    worktrees.WORKTREES_DIR = tmp_path / "wts"
    repo = _repo(tmp_path, "avec-develop", "master")
    _git(repo, "branch", "develop")

    assert worktrees.default_branch(str(repo)) == "develop"


def test_depot_sans_commit_rend_une_erreur_parlante(tmp_path):
    """HEAD non né : aucune base n'est résoluble, il ne faut PAS inventer `main`."""
    worktrees.WORKTREES_DIR = tmp_path / "wts"
    repo = tmp_path / "vide"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")

    assert worktrees.default_branch(str(repo)) == ""

    meta = worktrees.provision(str(repo), "tk-vide", with_venv=False)
    assert not meta["ok"]
    motif = (meta.get("error") or "").lower()
    assert "base" in motif and "invalid reference" not in motif, meta
