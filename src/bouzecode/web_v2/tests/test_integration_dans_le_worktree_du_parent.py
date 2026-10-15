# [desc] Un sous-agent intègre dans la branche de son parent, sortie dans le worktree du parent : fusion réelle, refus honnête, pas de boucle. [/desc]
"""Cas vécu le 2026-09-24 (portail des énigmes, DeepSeek) : le sous-agent appelait
`Environment(action='integrate')` vers `agent/<parent>`, sortie dans le worktree du parent.
git refusait (« cannot force update the branch … used by worktree »), l'outil répondait
« c'est re-tentable » et le modèle réessayait en boucle.

On appelle l'outil comme le harness (`_environment`) sur de vrais dépôts git."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.multi_agent import lancement_web
from bouzecode.backend.tools import environment
from bouzecode.web_v2.services.work import projects as work_projects
from bouzecode.web_v2.services.work import tickets as work_tickets

SLUG = "parentchild"


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _git_out(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def _commit(cwd: Path, name: str, contenu: str, message: str) -> None:
    (cwd / name).write_text(contenu, encoding="utf-8")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", message)


@pytest.fixture(autouse=True)
def _ardoise(monkeypatch):
    before = os.getcwd()
    monkeypatch.setattr(environment, "_ECHECS_INTEGRATION", {})
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    yield
    os.chdir(before)


@pytest.fixture()
def famille(tmp_path: Path, monkeypatch):
    """Dépôt + worktree du PARENT (branche agent/parent) + worktree de l'ENFANT (agent/enfant,
    parti de agent/parent), l'enfant porteur d'un ticket dont la base est la branche du parent."""
    repo = tmp_path / "depot"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    _commit(repo, "a.txt", "base\n", "init")

    parent = tmp_path / "wt-parent"
    _git(repo, "worktree", "add", "-b", "agent/parent", str(parent), "main")
    _commit(parent, "SPEC.md", "spec du parent\n", "parent : spec")
    enfant = tmp_path / "wt-enfant"
    _git(repo, "worktree", "add", "-b", "agent/enfant", str(enfant), "agent/parent")

    projects_path = tmp_path / "projects.json"
    monkeypatch.setattr(work_projects, "PROJECTS_PATH", projects_path)
    projects_path.write_text(json.dumps([{"slug": SLUG, "name": "PC", "path": str(repo)}]),
                             encoding="utf-8")
    ticket = work_tickets.create_ticket(SLUG, "enfant", "prompt")
    work_tickets.poser(SLUG, ticket, worktree={"repo_root": str(repo), "worktree": str(enfant),
                                               "branch": "agent/enfant", "base": "agent/parent"})
    #  L'enfant qui appelle l'outil est le run EN COURS de son ticket (lot L2 : `running`).
    work_tickets.set_launching(SLUG, ticket)
    work_tickets.add_run(SLUG, ticket, "enfant", "work", "m")
    ipc = tmp_path / "agents" / "enfant"
    ipc.mkdir(parents=True)
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", SLUG)
    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket["id"])
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", str(enfant))
    os.chdir(enfant)
    return repo, parent, enfant, {"_web_agent_dir": str(ipc)}


def _integrer(config: dict) -> str:
    return environment._environment({"action": "integrate"}, config)


def test_l_enfant_integre_dans_la_branche_sortie_par_son_parent(famille):
    """La fusion se fait DANS le worktree du parent : son commit y atterrit, sur sa branche."""
    repo, parent, enfant, config = famille
    _commit(enfant, "ui.html", "<p>tinder</p>\n", "enfant : ui")

    out = _integrer(config)

    assert "Merge propre" in out, out
    assert (parent / "ui.html").read_text(encoding="utf-8") == "<p>tinder</p>\n"
    assert "enfant : ui" in _git_out(repo, "log", "--format=%s", "agent/parent")
    assert "re-tentable" not in out


def test_parent_sale_refus_clair_sans_promettre_qu_un_nouvel_essai_marchera(famille):
    """Le parent a modifié SANS commiter le fichier que l'enfant apporte : refus explicite,
    le travail du parent est intact, et l'outil ne prétend pas que réessayer suffira."""
    repo, parent, enfant, config = famille
    _commit(enfant, "SPEC.md", "spec enrichie par l'enfant\n", "enfant : spec")
    (parent / "SPEC.md").write_text("brouillon du parent, non commité\n", encoding="utf-8")

    out = _integrer(config)

    assert "modifications non commitées" in out and "SPEC.md" in out, out
    assert "re-tentable" not in out and "telle quelle échouera" in out
    assert (parent / "SPEC.md").read_text(encoding="utf-8") == "brouillon du parent, non commité\n"
    assert "enfant : spec" not in _git_out(repo, "log", "--format=%s", "agent/parent")
    assert Path(os.getcwd()).resolve() == enfant.resolve(), "l'enfant reste chez lui"


def test_le_meme_echec_repete_dit_au_modele_d_arreter_d_insister(famille):
    repo, parent, enfant, config = famille
    _commit(enfant, "SPEC.md", "v enfant\n", "enfant : spec")
    (parent / "SPEC.md").write_text("wip parent\n", encoding="utf-8")

    premier = _integrer(config)
    second = _integrer(config)

    assert "N'insiste pas" not in premier
    assert "N'insiste pas" in second and "agent/enfant" in second and "FinalAnswer" in second


def test_deleguer_depuis_un_worktree_sale_previent_le_parent_et_l_enfant(famille, monkeypatch):
    """Le travail non commité du parent n'est pas dans la branche de l'enfant : le prompt de
    l'enfant dit où le lire, et le résultat de l'outil Agent le dit au parent."""
    repo, parent, enfant, config = famille
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", str(parent))
    (parent / "PLAN.md").write_text("plan non commité\n", encoding="utf-8")
    (parent / ".venv").mkdir()
    (parent / ".venv" / "bruit.txt").write_text("x", encoding="utf-8")
    envoye = {}

    def dispatch(body):
        envoye.update(body)
        return {"routed": True, "ticket_id": "t1", "project_slug": SLUG, "project_name": "PC"}

    out = lancement_web._spawn_web_ticket_agent(
        {"prompt": "Fais l'UI", "background": True}, {"_web_dispatch": dispatch})

    assert "PLAN.md" in envoye["prompt"] and str(parent) in envoye["prompt"]
    assert ".venv" not in envoye["prompt"]
    assert "PLAN.md" in out and "non commités" in out


def test_deleguer_depuis_un_worktree_propre_ne_dit_rien(famille, monkeypatch):
    repo, parent, enfant, config = famille
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", str(parent))
    envoye = {}

    def dispatch(body):
        envoye.update(body)
        return {"routed": True, "ticket_id": "t2", "project_slug": SLUG, "project_name": "PC"}

    out = lancement_web._spawn_web_ticket_agent(
        {"prompt": "Fais l'UI", "background": True}, {"_web_dispatch": dispatch})

    assert envoye["prompt"] == "Fais l'UI"
    assert "non commités" not in out
