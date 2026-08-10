# [desc] L'agent sait sur QUELLE branche il est, et une branche préexistante n'est jamais fauchée. [/desc]
"""Deux façons dont un travail juste devenait invisible.

1. L'agent ignorait sa branche. Son contrat de worktree ne nommait que le RÉPERTOIRE ; quand
   le ticket annonçait « ta branche de travail = agent/X » et que le provisioning avait sorti
   `agent/Y`, l'agent rapportait de bonne foi une livraison qui n'était pas là où on
   l'attendait. Le contrat cite maintenant la branche réellement sortie.
2. Le ménage de fin de ticket supprimait « la branche de l'agent ». Pour un travail EN PLACE,
   cette branche PRÉEXISTAIT et porte la livraison : la faucher détruirait le livrable."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.core import context
from bouzecode.web_v2.services.work import worktrees


# Identité passée par `-c` plutôt que par `git config` : écrire dans le .git/config d'un dépôt
# tout juste créé peut échouer (verrou) quand plusieurs workers xdist démarrent ensemble.
_IDENT = ["-c", "user.name=t", "-c", "user.email=t@t.t"]


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, f"git {' '.join(args)} : {done.stderr}"
    return done.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Un dépôt avec `develop` et une branche `feature/livree` déjà commencée."""
    root = tmp_path / "depot"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "develop", str(root)], capture_output=True)
    (root / "fichier.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "fichier.txt")
    _git(root, *_IDENT, "commit", "-qm", "base")
    _git(root, "branch", "feature/livree")
    return root


# ── l'agent sait où il travaille ─────────────────────────────────────────────

def test_le_contrat_de_worktree_nomme_la_branche_reellement_sortie(monkeypatch, tmp_path, repo):
    """Le system prompt d'un agent isolé cite la branche que git a VRAIMENT sortie."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    meta = worktrees.provision(str(repo), "t1", with_venv=False, work_branch="feature/livree")
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", meta["worktree"])

    volatile = context.build_system_prompt_parts()[1]

    assert "feature/livree" in volatile


def test_un_agent_sur_branche_neuve_voit_le_nom_de_sa_branche_neuve(monkeypatch, tmp_path, repo):
    """Cas nominal : le contrat nomme `agent/<ticket>`, pas la base dont il est parti."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    meta = worktrees.provision(str(repo), "t2", base_branch="feature/livree", with_venv=False)
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", meta["worktree"])

    volatile = context.build_system_prompt_parts()[1]

    assert "agent/t2" in volatile


def test_l_agent_est_invite_a_signaler_une_branche_qui_contredit_son_ticket(
        monkeypatch, tmp_path, repo):
    """Le contrat dit quoi faire d'une contradiction, au lieu de laisser l'agent l'ignorer."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    meta = worktrees.provision(str(repo), "t3", with_venv=False, work_branch="feature/livree")
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", meta["worktree"])

    volatile = context.build_system_prompt_parts()[1]

    assert "contradiction" in volatile


# ── le livrable n'est jamais fauché ──────────────────────────────────────────

def test_le_menage_ne_supprime_pas_une_branche_preexistante(monkeypatch, tmp_path, repo):
    """Après un travail EN PLACE, la branche demandée SURVIT au nettoyage du bac à sable."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    meta = worktrees.provision(str(repo), "t4", with_venv=False, work_branch="feature/livree")

    worktrees.cleanup(meta)

    assert _git(repo, "branch", "--list", "feature/livree") != "", "le livrable a été détruit"


def test_le_menage_supprime_toujours_une_branche_d_agent_jetable(monkeypatch, tmp_path, repo):
    """Cas nominal intact : la branche `agent/<ticket>`, elle, est bien fauchée."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    meta = worktrees.provision(str(repo), "t5", with_venv=False)

    worktrees.cleanup(meta)

    assert _git(repo, "branch", "--list", "agent/t5") == ""


def test_un_travail_en_place_est_deja_integre(monkeypatch, tmp_path, repo):
    """Rien à merger : la livraison est déjà sur la branche demandée."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    meta = worktrees.provision(str(repo), "t6", with_venv=False, work_branch="feature/livree")
    worktree = Path(meta["worktree"])
    (worktree / "fichier.txt").write_text("base\ncorrection\n", encoding="utf-8")
    _git(worktree, "add", "fichier.txt")
    _git(worktree, *_IDENT, "commit", "-qm", "correction")

    assert worktrees.integrate(meta)["state"] == "integrated"


def test_le_diff_livre_montre_ce_que_l_agent_a_ajoute(monkeypatch, tmp_path, repo):
    """La récolte d'un travail EN PLACE n'est pas vide : le validateur voit bien la livraison."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    meta = worktrees.provision(str(repo), "t7", with_venv=False, work_branch="feature/livree")
    (Path(meta["worktree"]) / "fichier.txt").write_text("base\ncorrection\n", encoding="utf-8")

    assert "correction" in worktrees.harvest(meta, "la correction")["diff"]
