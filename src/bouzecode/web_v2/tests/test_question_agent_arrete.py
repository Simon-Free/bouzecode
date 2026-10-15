"""Question d'un agent ARRÊTÉ : classable sans réponse, ou reprise proposée (Bureau, 2026-10-13).

Constat : des questions d'agents dont le process est mort restaient éternellement dans
« À traiter ». L'humain doit pouvoir choisir : classer la carte (avec commentaire), ou reprendre
l'agent en mode « continuer ». La question d'un agent VIVANT, elle, ne change pas.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import awaiting
from bouzecode.web_v2.tests.test_killed_agent_stops_waiting import (  # noqa: F401 — fixtures
    _caches_neufs, _write_paused_agent, parc)


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _ids(**kw):
    return [r["agent_id"] for r in awaiting.agents_awaiting_answer(**kw)]


def _vider_caches():
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import store
    agent_fiche._list_agents_cache.clear()
    store._status_cache.clear()


def _cartes(noeud):
    """Toutes les cartes (dict avec `agent_id` et `actions`) d'une réponse /api/inbox."""
    if isinstance(noeud, dict):
        if "agent_id" in noeud and "actions" in noeud:
            yield noeud
        for v in noeud.values():
            yield from _cartes(v)
    elif isinstance(noeud, list):
        for v in noeud:
            yield from _cartes(v)


def test_question_d_agent_arrete_archivable_sans_reponse(parc, client):
    _write_paused_agent(parc, "mort0000001")
    assert "mort0000001" in _ids()
    r = client.post("/api/agents/mort0000001/question/archive",
                    json={"comment": "plus d'actualité"})
    assert r.status_code == 200, r.get_json()
    _vider_caches()
    assert "mort0000001" not in _ids()
    # La question n'est pas supprimée : elle reste lisible avec son archivage.
    assert "mort0000001" in _ids(include_archived=True)
    cartes = [c for c in _cartes(client.get("/api/inbox").get_json())
              if c["agent_id"] == "mort0000001"]
    assert cartes == []


def test_reprise_proposee_sur_carte_d_agent_arrete(parc, client):
    _write_paused_agent(parc, "mort0000002")
    cartes = [c for c in _cartes(client.get("/api/inbox").get_json())
              if c["agent_id"] == "mort0000002"]
    assert cartes, "la question de l'agent arrêté doit apparaître dans À traiter"
    carte = cartes[0]
    assert carte["agent_vivant"] is False
    assert {"repondre", "continuer", "archiver"} <= set(carte["actions"])


def test_question_d_agent_vivant_inchangee(parc):
    """Un agent VIVANT n'est jamais filtré, même si sa question a été classée, et sa carte
    n'offre ni « archiver » ni « continuer » : la réponse part normalement."""
    from bouzecode.web_v2.services.work import decisions, inbox
    decisions.archive_question("vivant00001", "2026-09-21T10:00:00+00:00", "x")
    row = {"agent_id": "vivant00001", "asked_at": "2026-09-21T10:00:00+00:00", "warm": True}
    mort = {**row, "agent_id": "mort0000009", "warm": False}
    decisions.archive_question("mort0000009", "2026-09-21T10:00:00+00:00", "x")
    assert [r["agent_id"] for r in awaiting._sans_archivees([row, mort])] == ["vivant00001"]
    actions = inbox._actions_question(True)
    assert "repondre" in actions
    assert "archiver" not in actions and "continuer" not in actions


def test_archiver_agent_qui_n_attend_rien_refuse(parc, client):
    r = client.post("/api/agents/inconnu0001/question/archive", json={})
    assert r.status_code == 404


def test_nouvelle_question_reapparait_apres_archivage(parc, client):
    """L'archivage vise UNE question (agent, asked_at) : une question suivante revient."""
    from bouzecode.web_v2.services.work import decisions
    _write_paused_agent(parc, "mort0000003")
    assert client.post("/api/agents/mort0000003/question/archive", json={}).status_code == 200
    classees = decisions.archived_questions()
    assert any(a == "mort0000003" for a, _ in classees)
    decisions.archive_question("mort0000003", "autre-date", "")
    _vider_caches()
    assert "mort0000003" not in _ids()
