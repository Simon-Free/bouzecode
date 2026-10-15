# [desc] L'isolation demandée est respectée ou refusée (jamais changée d'office) ; un refus de collision se lit sans jargon et dit quoi faire. [/desc]
"""Avant le lot L3, un dépôt occupé faisait basculer l'agent en worktree d'office, et un toast
expliquait ce changement. Désormais (spec §5.1, C8) le serveur ne change plus l'environnement
demandé : un `shared` en collision est refusé (409 `collision_isolation`) en nommant les agents
qui écrivent et le remède ; un environnement retenu n'a rien à annoncer."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.runtime.runner import agent_registre
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import dispatch, projects


class _Agent:
    def __init__(self, agent_id: str, cwd: str, profile: str):
        self.agent_id, self.cwd, self.profile = agent_id, cwd, profile


@pytest.fixture()
def depot(tmp_path: Path) -> Path:
    root = tmp_path / "depot"
    root.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@t.t"), ("config", "user.name", "t")):
        assert subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0
    return root


@pytest.fixture()
def lancer(monkeypatch, depot):
    """POST /api/projects/{slug}/tickets réel ; seul le lancement en fond est neutralisé."""
    from bouzecode.web_v2.app import create_app

    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(dispatch, "_launch_bg", lambda *args: None)
    assert isinstance(projects.add_project("depot", str(depot)), dict)
    app = create_app()
    app.config["TESTING"] = True

    def _post(isolation: str = "shared"):
        with app.test_client() as client:
            return client.post("/api/projects/depot/tickets", json={
                "title": "Corrige le bug", "prompt": "Corrige le bug\nDétails.",
                "isolation": isolation, "defer": True})

    return _post


def _occuper(monkeypatch, depot: Path) -> None:
    agents = [_Agent("codeur-en-place", str(depot), "coder")]
    monkeypatch.setattr(agent_registre, "list_agents", lambda: agents)
    monkeypatch.setattr(store, "agent_status", lambda a: {"state": "running"})


def test_un_depot_occupe_refuse_le_shared_et_dit_quoi_faire(lancer, monkeypatch, depot):
    """Un codeur écrit déjà dans le dépôt : refus lisible, qui nomme l'occupant et le remède ;
    aucun ticket n'est créé, rien n'est basculé."""
    _occuper(monkeypatch, depot)

    reponse = lancer()

    assert reponse.status_code == 409
    erreur = reponse.get_json()["error"]
    assert erreur["code"] == "collision_isolation"
    assert erreur["details"]["agents"] == ["codeur-en-place"]
    assert "worktree" in erreur["message"] and "jamais" in erreur["message"]
    for jargon in ("ÉCRIVAIN", "garde-fou"):
        assert jargon not in erreur["message"], f"jargon « {jargon} » montré à l'utilisateur"


def test_le_worktree_demande_passe_meme_dans_un_depot_occupe(lancer, monkeypatch, depot):
    _occuper(monkeypatch, depot)

    reponse = lancer("worktree")

    assert reponse.status_code == 201 and reponse.get_json()["isolation"] == "worktree"


def test_aucun_message_quand_l_environnement_demande_est_retenu(lancer, monkeypatch):
    """Dépôt libre : rien n'a changé, donc rien à annoncer."""
    monkeypatch.setattr(agent_registre, "list_agents", lambda: [])

    reponse = lancer()

    assert reponse.status_code == 201
    assert reponse.get_json()["isolation"] == "shared"
    assert reponse.get_json()["isolation_message"] == ""
