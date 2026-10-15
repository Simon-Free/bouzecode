# [desc] ListAgentTasks d'un agent web liste ses sous-agents lancés via le serveur (tickets), lus dans l'arbre réellement servi. [/desc]
"""Recette du 2026-09-24 : un manager qui déléguait via l'outil Agent (→ tickets du serveur)
appelait ListAgentTasks et recevait « No sub-agent tasks » alors que ses deux enfants
tournaient — le gestionnaire local ne connaît que les sous-agents in-process."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.backend.multi_agent.outils_enfants import _list_agent_tasks


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _agent(agent_id: str, parent: str, titre: str) -> None:
    session = agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"
    session.write_text(json.dumps({"messages": [{"role": "user", "content": titre}]}),
                       encoding="utf-8")
    ipc = agent_fiche.AGENTS_DIR / f"{agent_id}.ipc"
    ipc.mkdir(exist_ok=True)
    agent_fiche._save(agent_fiche.Agent(
        agent_id=agent_id, prompt=titre, model="", cwd=str(agent_fiche.AGENTS_DIR), pid=0,
        started_at="2026-09-24T10:00:00Z", finished_at="2026-09-24T10:01:00Z", returncode=0,
        stdout_path=str(agent_fiche.AGENTS_DIR / f"{agent_id}.out.log"), session_path=str(session),
        ipc_dir=str(ipc), parent=parent,
    ))


def test_le_manager_voit_ses_enfants_lances_par_le_serveur(client):
    _agent("manager01", "dispatcher:manual", "Coordonner deux lots")
    _agent("enfanta01", "manager01", "Enfant A : écrire enfant_a.md")
    _agent("autre0001", "quelquun", "Hors sujet")

    def get(url):
        chemin = url.split("127.0.0.1", 1)[-1].split("/", 1)[-1]
        return client.get("/" + chemin).get_json()

    sortie = _list_agent_tasks({}, {"_web_agent_dir": str(agent_fiche.AGENTS_DIR / "manager01.ipc"),
                                    "_web_get": get})

    assert "enfanta01" in sortie
    assert "autre0001" not in sortie
    assert "No sub-agent tasks" not in sortie


def test_sans_enfant_la_reponse_reste_explicite(client, monkeypatch):
    from bouzecode.backend.multi_agent import gestionnaire
    from bouzecode.backend.multi_agent.manager import SubAgentManager
    #  Le gestionnaire local est un singleton de process : un autre test a pu y laisser des tâches.
    monkeypatch.setattr(gestionnaire, "get_agent_manager", lambda: SubAgentManager())
    _agent("seul00001", "dispatcher:manual", "Seul")

    def get(url):
        return client.get("/api/agents/tree").get_json()

    sortie = _list_agent_tasks({}, {"_web_agent_dir": str(agent_fiche.AGENTS_DIR / "seul00001.ipc"),
                                    "_web_get": get})
    assert sortie == "No sub-agent tasks."
