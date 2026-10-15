# [desc] Un enfant parti en partagé qui s'isole en vol est vu DANS son worktree, et un agent en worktree voit son vrai dépôt. [/desc]
"""Essai du 2026-09-24 (bouzeui, HOME serveur = ~/bouzecode-essai).

L'agent racine travaillait dans `~/bouzecode-essai/.bouzecode/worktrees/portail-enigmes/<id>`.
Son contexte de session ne citait que ce chemin : il en a déduit que son dépôt était la partie
avant `/.bouzecode/` — le HOME — et l'a dicté à son enfant (« Tu es dans le dépôt git
`/home/simon/bouzecode-essai` »). L'enfant, lancé en partagé dans `~/portail-enigmes`, s'est
ensuite isolé lui-même (`Environment(action='worktree')`, branche `agent/<ticket>`) ; sa fiche
serveur (`web_agents/<id>.json`) gardait pourtant `cwd = ~/portail-enigmes` tant qu'il tournait.

Vrais services : l'outil `Environment` tel que le harnais l'appelle, le vrai store de tickets,
le vrai provisionnement git, `runner.list_agents` (ce que lisent l'arbre et le garde-fou) et le
garde-fou d'isolation du dispatch. Aucun LLM : le process de l'agent est un `sleep`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.backend.core import context
from bouzecode.backend.tools import environment
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.work import isolation
from bouzecode.web_v2.services.work import projects as work_projects
from bouzecode.web_v2.services.work import tickets as work_tickets

SLUG = "portail"


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _restore_cwd():
    before = os.getcwd()
    yield
    os.chdir(before)


@pytest.fixture()
def depot(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "portail-enigmes"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "user.email", "t@t")
    (path / "a.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-m", "init")
    projects_path = tmp_path / "work_projects.json"
    monkeypatch.setattr(work_projects, "PROJECTS_PATH", projects_path)
    projects_path.write_text(
        json.dumps([{"slug": SLUG, "name": "portail-enigmes", "path": str(path)}]),
        encoding="utf-8")
    return path


@pytest.fixture()
def process_vivant():
    """Le process de l'agent : vivant pendant le test, comme un enfant en plein travail."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proc.pid
    proc.kill()
    proc.wait(timeout=10)


def _fiche(agents_dir: Path, depot: Path, pid: int, ticket_id: str = "") -> agent_fiche.Agent:
    """La fiche que `dispatch._launch` écrit pour un enfant `shared` : cwd = le dépôt."""
    agent_id = "enfant1"
    ipc = agents_dir / f"{agent_id}.ipc"
    ipc.mkdir(parents=True)
    agent = agent_fiche.Agent(
        agent_id=agent_id, prompt="Corrige l'énigme 3", model="", cwd=str(depot), pid=pid,
        started_at="2026-09-24T10:00:00Z", stdout_path=str(agents_dir / f"{agent_id}.out.log"),
        session_path=str(agents_dir / f"{agent_id}.session.json"), ipc_dir=str(ipc),
        parent="racine1", ticket_slug=SLUG if ticket_id else "", ticket_id=ticket_id)
    agent_fiche._save(agent)
    return agent


def _isoler_en_vol(agent: agent_fiche.Agent, monkeypatch) -> str:
    """Ce que fait l'enfant dans SON process : Environment(action='worktree')."""
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", agent.ticket_slug)
    monkeypatch.setenv("BOUZECODE_TICKET_ID", agent.ticket_id)
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    os.chdir(agent.cwd)
    out = environment._environment({"action": "worktree"}, {"_web_agent_dir": agent.ipc_dir})
    assert "Worktree dédié créé et adopté" in out, out
    return os.getcwd()


def test_la_fiche_de_l_enfant_suit_son_worktree_pendant_qu_il_tourne(
        depot, process_vivant, monkeypatch):
    ticket = work_tickets.create_ticket(SLUG, "Énigme 3", "Corrige l'énigme 3")
    agent = _fiche(agent_fiche.AGENTS_DIR, depot, process_vivant, ticket["id"])

    worktree = _isoler_en_vol(agent, monkeypatch)

    vu = next(a for a in agent_registre.list_agents() if a.agent_id == agent.agent_id)
    fichier = json.loads((agent_fiche.AGENTS_DIR / f"{agent.agent_id}.json").read_text("utf-8"))
    assert Path(vu.cwd).resolve() == Path(worktree).resolve()
    assert Path(fichier["cwd"]).resolve() == Path(worktree).resolve(), (
        "la fiche web_agents/<id>.json doit désigner le worktree, pas le dépôt principal")
    assert Path(fichier["worktree_root"]).resolve() == Path(worktree).resolve()
    # Conséquence au dispatch suivant : l'enfant n'écrit plus dans l'arbre partagé, un frère
    # lancé en `shared` n'a donc aucune raison d'être relevé en worktree.
    assert isolation.resolve_isolation(str(depot), isolation.SHARED)[0] == isolation.SHARED


def test_un_agent_sans_ticket_isole_en_vol_transmet_encore_son_projet(
        depot, process_vivant, monkeypatch):
    """Sa fiche suit désormais le worktree (hors du dossier du projet) : l'héritage du projet
    par ses enfants doit passer par le dépôt de ce worktree."""
    agent = _fiche(agent_fiche.AGENTS_DIR, depot, process_vivant)
    _isoler_en_vol(agent, monkeypatch)
    agent_registre.list_agents()

    from bouzecode.web_v2.services.work.api_tickets import agents_vue
    assert agents_vue.fiche(agent.agent_id)["project_slug"] == SLUG


def test_un_agent_en_worktree_voit_son_vrai_depot(depot, tmp_path, monkeypatch):
    """Le worktree vit sous `<HOME>/.bouzecode/worktrees/` : le contexte de session doit nommer
    le dépôt, sinon le modèle prend le HOME pour son dépôt."""
    home = tmp_path / "bouzecode-essai"
    worktree = home / ".bouzecode" / "worktrees" / "portail-enigmes" / "4016d313"
    _git(depot, "worktree", "add", "-b", "agent/4016d313", str(worktree))

    os.chdir(worktree)
    dans_le_worktree = context.build_session_context({})
    os.chdir(depot)
    dans_le_depot = context.build_session_context({})

    assert f"Dépôt git : {depot}" in dans_le_worktree
    assert "Dépôt git" not in dans_le_depot
