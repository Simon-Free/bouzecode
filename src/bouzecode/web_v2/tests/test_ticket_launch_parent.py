# [desc] La relance d'un ticket (retry crashé/reapé) rattache l'agent au parent d'origine du ticket. [/desc]
"""Régression FIX orphelin de reprise : api_ticket_launch appelait create_agent SANS parent →
l'agent de reprise naissait orphelin (parent="") → invisible dans l'arbre du manager parent →
son digest restait figé. On vérifie, via le client Flask RÉEL, que create_agent reçoit
parent = ticket['parent']. Seuls les lookups (_project_or_404/_ticket_or_404) et create_agent
sont faked ; la route reste réelle. No unittest.mock."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture()
def client(monkeypatch):
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.routes.work import tickets as troute

    captured: dict = {}
    ticket = {"id": "tk1", "prompt": "fix it", "parent": "mgr-42", "runs": []}

    monkeypatch.setattr(troute, "_project_or_404",
                        lambda slug: ({"path": ".", "name": "P", "slug": slug}, None))
    monkeypatch.setattr(troute, "_ticket_or_404", lambda slug, tid: (ticket, None))
    monkeypatch.setattr(troute.tickets, "add_run", lambda *a, **k: None)

    def _create_agent(prompt, model, cwd, **kw):
        captured["parent"] = kw.get("parent")
        return SimpleNamespace(agent_id="child-1")

    monkeypatch.setattr(troute.runner, "create_agent", _create_agent)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c._captured = captured
        yield c


def test_relaunch_inherits_ticket_parent(client):
    r = client.post("/api/tickets/proj/tk1/launch", json={})  # pas d'isolate → chemin minimal
    assert r.status_code == 200
    assert client._captured["parent"] == "mgr-42"  # rattaché, pas orphelin
