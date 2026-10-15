# [desc] La récolte automatique ne committe jamais un merge inachevé ni les fichiers internes du harnais (vrais dépôts git). [/desc]
"""Constaté sur un vrai dépôt : une récolte automatique (`git add -A` + commit) a committé un
merge en conflit — commit d1500e9, trois marqueurs `<<<<<<<` dans tinder.html — ainsi que le
plan interne du harnais `.nano_claude/plans/<session>.md`, depuis suivi dans main."""
from __future__ import annotations

import subprocess
from pathlib import Path

from bouzecode.backend.core.harness_dir import dossier_harnais
from bouzecode.web_v2.services.work import delivery, worktrees
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import run, semer


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                         capture_output=True, text=True)
    return res.stdout.strip()


def _depot(tmp_path: Path) -> Path:
    repo = tmp_path / "depot"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "page.html").write_text("<p>base</p>\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _meta(repo: Path) -> dict:
    return {"worktree": str(repo), "base": "main", "branch": _git(repo, "branch", "--show-current"),
            "repo_root": str(repo)}


def _merge_en_conflit(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "agent/x")
    (repo / "page.html").write_text("<p>agent</p>\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "agent")
    _git(repo, "checkout", "-q", "main")
    (repo / "page.html").write_text("<p>main</p>\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "main")
    _git(repo, "checkout", "-q", "agent/x")
    _git(repo, "merge", "main")                     # conflit : page.html a des marqueurs


def test_la_recolte_ne_committe_pas_un_merge_en_conflit(tmp_path):
    """Merge inachevé dans le worktree : aucun commit, et la raison est dite avec les fichiers."""
    repo = _depot(tmp_path)
    _merge_en_conflit(repo)
    avant = _git(repo, "rev-parse", "HEAD")

    recolte = worktrees.harvest(_meta(repo), "tâche")

    assert recolte["committed"] is False
    assert _git(repo, "rev-parse", "HEAD") == avant
    assert recolte["bloque"]["fichiers"] == ["page.html"]
    assert "un merge est en cours" in recolte["bloque"]["message"]
    assert "<<<<<<<" not in _git(repo, "show", "HEAD:page.html")


def test_des_marqueurs_de_conflit_hors_merge_bloquent_aussi(tmp_path):
    """Marqueurs laissés dans un fichier (merge déjà abandonné à la main) : rien n'est committé."""
    repo = _depot(tmp_path)
    (repo / "page.html").write_text("<<<<<<< HEAD\na\n=======\nb\n>>>>>>> main\n", encoding="utf-8")

    recolte = worktrees.harvest(_meta(repo), "tâche")

    assert recolte["committed"] is False and recolte["bloque"]["fichiers"] == ["page.html"]


def test_les_plans_du_harnais_ne_sont_jamais_committes(tmp_path):
    """Un plan écrit par le harnais dans le dépôt n'entre ni dans git status ni dans le commit récolté."""
    repo = _depot(tmp_path)
    (dossier_harnais("plans", cwd=repo) / "abc.md").write_text("# Plan\n", encoding="utf-8")
    (repo / "page.html").write_text("<p>travail</p>\n", encoding="utf-8")

    recolte = worktrees.harvest(_meta(repo), "tâche")

    assert recolte["committed"] is True and recolte["bloque"] is None
    suivis = _git(repo, "ls-files").splitlines()
    assert "page.html" in suivis and not any(".nano_claude" in f for f in suivis)
    assert ".nano_claude" not in _git(repo, "status", "--porcelain")


def test_on_ne_detruit_pas_un_worktree_dont_la_recolte_est_suspendue(tmp_path):
    """Avant d'archiver/réclamer un worktree : merge inachevé → refus (False) et raison sur le
    ticket livré (`state_reason`, lot L2), persistée."""
    repo = _depot(tmp_path)
    _merge_en_conflit(repo)
    ticket = semer("proj", "t1", etats.DELIVERED, title="tâche", worktree=_meta(repo),
                   runs=[run("a1", completed=True)])

    assert delivery.harvest_before_reclaiming("proj", ticket) is False
    raison = delivery.tickets_svc.get_ticket("proj", "t1")["state_reason"]
    assert raison["code"] == delivery.NON_COMMITEE and "Récolte suspendue" in raison["message"]


def test_un_marqueur_deja_committe_ne_suspend_pas_la_recolte(tmp_path):
    """Un fichier suivi qui contient légitimement un marqueur (fixture, doc) ne bloque pas :
    seule une résolution en cours ou un marqueur introduit par le travail non commité compte."""
    repo = _depot(tmp_path)
    (repo / "fixture.txt").write_text("<<<<<<< HEAD\na\n=======\nb\n>>>>>>> main\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture de conflit")
    (repo / "page.html").write_text("<p>travail</p>\n", encoding="utf-8")

    recolte = worktrees.harvest(_meta(repo), "tâche")

    assert recolte["bloque"] is None and recolte["committed"] is True
