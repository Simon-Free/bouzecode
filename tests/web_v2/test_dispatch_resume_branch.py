# [desc] resume_branch : le worktree d'un dispatch est créé DEPUIS une branche existante
# (reprise de travail) au lieu de develop, et un resume force TOUJOURS l'isolation.
# Vrai git sur repo temp + fakes purs, zéro agent LLM. [/desc]
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.services.work import dispatch, provisioning
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import worktrees


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _commit(cwd, msg):
    _git(cwd, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", msg)


def _make_repo(root: Path) -> Path:
    """Repo git : develop (commit A) + branche annexe 'reprise' avec un commit dédié."""
    repo = root / "primary"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "develop")
    (repo / "f.txt").write_text("A\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _commit(repo, "A")
    _git(repo, "checkout", "-q", "-b", "reprise")
    (repo / "reprise.txt").write_text("work-in-progress\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _commit(repo, "travail repris")
    _git(repo, "checkout", "-q", "develop")
    return repo


def test_provision_uses_given_base_branch(tmp_path, monkeypatch):
    """provision(base_branch=<branche annexe>) crée agent/<ticket> descendant de cette base."""
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wt")

    meta = worktrees.provision(str(repo), "t1", base_branch="reprise", with_venv=False)

    assert meta["ok"] is True
    assert meta["base"] == "reprise"
    assert meta["branch"] == "agent/t1"
    # Le worktree descend bien de 'reprise' : il porte le fichier du travail repris.
    assert (Path(meta["worktree"]) / "reprise.txt").is_file()


def _wire_provision(monkeypatch, tmp_path, captured: dict) -> None:
    """Fakes communs aux deux tests de base de worktree.

    Le store est redirigé vers `tmp_path` : `_provision_worktree` rattache le worktree au
    ticket via `tickets.update_ticket`, qui écrit RÉELLEMENT — sans cette redirection le
    test toucherait la base de tickets de PRODUCTION.
    """
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(dispatch.repos, "repo_root", lambda p: "/root")
    # `**_` : ces doubles n'ont AUCUNE raison de casser quand la vraie fonction gagne un
    # paramètre. `setup_venv_async` a reçu un `on_result` en cours de route, et chaque faux
    # à signature figée a dû être retouché pour un argument qu'aucun test ne lit.
    monkeypatch.setattr(provisioning.worktrees, "setup_venv_async", lambda wt, root="", **_: None)

    def fake_provision(root, ticket_id, base_branch="", with_venv=True, **_):
        captured["base_branch"] = base_branch
        return {"ok": True, "worktree": "/wt", "repo_root": root}  # provision réelle renvoie repo_root

    monkeypatch.setattr(provisioning.worktrees, "provision", fake_provision)


def test_provision_worktree_forwards_resume_branch(monkeypatch, tmp_path):
    """`_provision_worktree` transmet resume_branch à provision comme base_branch.

    Anciennement `_maybe_isolate(…, with_venv)` : le venv n'est plus un booléen mais un mode
    d'isolation (`worktree` vs `worktree+venv`). Le contrat testé ici est INCHANGÉ."""
    captured: dict = {}
    _wire_provision(monkeypatch, tmp_path, captured)

    cwd = dispatch._provision_worktree("p", {"id": "t9"}, "/proj", "agent/old")

    assert captured["base_branch"] == "agent/old"
    assert cwd == "/wt"


def test_provision_worktree_defaults_to_live_branch(monkeypatch, tmp_path):
    """(fix) sans resume_branch, la base du worktree = la branche VIVE du dépôt (ce que le
    serveur exécute), plus 'develop' hardcodé — sinon l'agent développe sur une branche que
    le serveur ne sert pas."""
    captured: dict = {}
    _wire_provision(monkeypatch, tmp_path, captured)
    monkeypatch.setattr(provisioning.worktrees, "current_branch", lambda root: "session/live")

    dispatch._provision_worktree("p", {"id": "t9"}, "/proj")  # resume_branch omis

    assert captured["base_branch"] == "session/live"


def test_dispatch_resume_branch_forces_isolation(monkeypatch, tmp_path):
    """dispatch(resume_branch=...) force un worktree et propage la branche au launch.

    Le booléen `do_isolate` a laissé place au mode `isolation` ('shared'/'worktree'/
    'worktree+venv'), RÉSOLU par `resolve_isolation` : une reprise de branche exige
    structurellement un worktree, donc le mode remis à `_launch` ne peut pas être 'shared'.

    Le projet doit être un VRAI dépôt git : `resolve_isolation` teste « est-ce un dépôt ? »
    AVANT « un worktree est-il exigé ? » et rend `shared` sur un dossier quelconque. Avec
    l'ancien booléen passé tel quel, un `tmp_path` nu suffisait ; il ne suffit plus, et un
    test qui ne traverse pas la vraie résolution ne prouverait plus le contrat."""
    project = {"slug": "p", "name": "Projet", "path": str(_make_repo(tmp_path))}
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(dispatch.projects, "list_projects", lambda: [project])
    monkeypatch.setattr(dispatch.projects, "find", lambda slug: project)
    monkeypatch.setattr(dispatch, "get_typology",
                        lambda name, path: {"profile": "", "default_model": ""})

    launched = threading.Event()
    captured: dict = {}

    def fake_launch(slug, ticket, project_path, profile, model, isolation=dispatch.SHARED,
                    parent="", resume_branch="", work_branch=""):
        captured["isolation"] = isolation
        captured["resume_branch"] = resume_branch
        launched.set()

    monkeypatch.setattr(dispatch, "_launch", fake_launch)

    dispatch.dispatch("reprends le boulot", project_slug="p", typology="default",
                      defer=True, resume_branch="agent/old")

    assert launched.wait(3)
    assert captured["isolation"] != dispatch.SHARED  # resume EXIGE un worktree
    assert captured["resume_branch"] == "agent/old"
