# [desc] La relance d'un ticket (retry crashé/reapé) rattache l'agent au parent d'origine du ticket. [/desc]
"""Régression FIX orphelin de reprise : la relance (ex-api_ticket_launch, désormais POST …/runs) appelait create_agent SANS parent →
l'agent de reprise naissait orphelin (parent="") → invisible dans l'arbre du manager parent →
son digest restait figé. On vérifie, via le client Flask RÉEL, que create_agent reçoit
parent = ticket['parent']. Le ticket est un vrai ticket du store (lot L2 : le lancement est une
transition) ; seul create_agent est faked (aucun process lancé). No unittest.mock."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.runtime.runner import agent_creation
    from bouzecode.web_v2.services.work import tickets
    from bouzecode.web_v2.tests.aides_tickets import projet

    captured: dict = {}
    projet(tmp_path, monkeypatch, "proj")
    ticket = tickets.create_ticket("proj", "T", "fix it")
    tickets.poser("proj", ticket, parent="mgr-42")
    captured["ticket_id"] = ticket["id"]

    def _create_agent(prompt, model, cwd, **kw):
        captured["parent"] = kw.get("parent")
        return SimpleNamespace(agent_id="child-1")

    monkeypatch.setattr(agent_creation, "create_agent", _create_agent)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c._captured = captured
        yield c


def test_relaunch_inherits_ticket_parent(client):
    r = client.post(f"/api/projects/proj/tickets/{client._captured['ticket_id']}/runs",
                    json={"defer": False})
    assert r.status_code == 202, r.get_json()
    assert client._captured["parent"] == "mgr-42"  # rattaché, pas orphelin
