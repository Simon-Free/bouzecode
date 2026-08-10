# [desc] POST /api/agents/<id>/continue : re-home le cwd (worktree nettoyé) AVANT respawn, pour ne
# plus crasher en 500. No unittest.mock — fakes purs + monkeypatch. [/desc]
from __future__ import annotations

import pytest

from bouzecode.web_v2.runtime import runner


def _agent():
    return runner.Agent(agent_id="a1", prompt="p", model="", cwd="/gone", pid=0,
                        started_at="", session_path="/tmp/a1.session.json",
                        ticket_slug="proj", ticket_id="tk1")


@pytest.fixture()
def client(monkeypatch):
    from bouzecode.web_v2.runtime import pending
    from bouzecode.web_v2.routes import sessions as routes
    from bouzecode.web_v2.services.sessions import store
    from bouzecode.web_v2.services.work import dispatch

    calls = []
    agent = _agent()
    monkeypatch.setattr(runner, "load_agent", lambda aid: agent if aid == "a1" else None)
    monkeypatch.setattr(store, "agent_status", lambda a: {"state": "finished"})
    monkeypatch.setattr(pending, "exists", lambda sp: False)
    monkeypatch.setattr(dispatch, "rehome_agent_cwd",
                        lambda a: calls.append(("rehome", a.agent_id)) or "/fresh/wt")
    # `continue_agent` rend l'agent RELANCÉ (et None seulement quand la relance a été
    # refusée) : le faux doit dire la même chose, sinon la route conclut à juste titre que
    # rien n'a été remis et répond 409.
    monkeypatch.setattr(runner, "continue_agent",
                        lambda a, text: calls.append(("continue", text)) or a)

    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c._calls = calls  # type: ignore[attr-defined]
        yield c


def test_continue_rehomes_before_respawn(client):
    """Un agent fini dont le worktree a été nettoyé : /continue re-home le cwd PUIS respawn,
    et renvoie 200 (plus le 500 déguisé en 'interromps l'agent')."""
    resp = client.post("/api/agents/a1/continue", json={"text": "précision"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    # rehome AVANT continue, dans cet ordre.
    assert client._calls == [("rehome", "a1"), ("continue", "précision")]


def test_continue_empty_text_reprend(client):
    """Le bouton "Reprendre" POST {text:""} sur un agent crashé/fini : NE renvoie PLUS 400
    ("texte requis"). text vide est légitime (relance sans nouveau message) — continue_agent
    rejoue le prompt d'origine. On re-home puis relance."""
    resp = client.post("/api/agents/a1/continue", json={"text": ""})

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    assert client._calls == [("rehome", "a1"), ("continue", "")]


def test_continue_unknown_agent_404(client):
    resp = client.post("/api/agents/nope/continue", json={"text": "x"})
    assert resp.status_code == 404
    assert client._calls == []


def test_continue_relaunches_reaped_ticket(client):
    """Ticket mergé/reapé → /continue NE refuse PLUS : il re-home vers un worktree frais PUIS
    relance l'agent (rehome_agent_cwd/reisolate recrée un arbre vivant off base branch)."""
    resp = client.post("/api/agents/a1/continue", json={"text": "fais X"})

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    # rehome AVANT continue, dans cet ordre — relance effective, pas d'erreur.
    assert client._calls == [("rehome", "a1"), ("continue", "fais X")]
