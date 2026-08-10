# [desc] POST /api/agents/<id>/continue : répondre à une question (AskUserQuestion OU validation de
# plan) reprend le tour EN PAUSE, et une remise qui n'a pas eu lieu n'est jamais annoncée OK. [/desc]
from __future__ import annotations

import pytest

from bouzecode.web_v2.runtime import runner


def _agent():
    return runner.Agent(agent_id="a1", prompt="p", model="", cwd="/live", pid=0,
                        started_at="", session_path="/tmp/a1.session.json")


@pytest.fixture()
def make_client(monkeypatch):
    """Fabrique un client dont on choisit l'état de l'agent et ce que rendent les
    fonctions de remise (`resume_pending_agent` / `continue_agent`)."""
    from bouzecode.web_v2.runtime import pending
    from bouzecode.web_v2.services.sessions import store
    from bouzecode.web_v2.services.work import dispatch

    def build(state: str, pending_present: bool = True, delivered=_agent()):
        calls = []
        agent = _agent()
        monkeypatch.setattr(runner, "load_agent", lambda aid: agent if aid == "a1" else None)
        monkeypatch.setattr(store, "agent_status", lambda a: {"state": state})
        monkeypatch.setattr(store, "invalidate_status", lambda aid: None)
        monkeypatch.setattr(pending, "exists", lambda sp: pending_present)
        monkeypatch.setattr(dispatch, "rehome_agent_cwd", lambda a: a.cwd)
        monkeypatch.setattr(runner, "resume_pending_agent",
                            lambda a, text: calls.append(("resume", text)) or delivered)
        monkeypatch.setattr(runner, "continue_agent",
                            lambda a, text: calls.append(("continue", text)) or delivered)

        from bouzecode.web_v2.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        client._calls = calls  # type: ignore[attr-defined]
        return client

    return build


def test_validation_de_plan_reprend_le_tour_en_pause(make_client):
    """Un plan à valider est une QUESTION : la réponse doit reprendre le tour en pause
    (`resume_pending_agent` → --resume-pending / answer.txt), pas ouvrir un tour neuf.
    En partant en `continue_agent`, le `<session>.pending.json` n'était jamais consommé et
    la conversation restait « à répondre » pour toujours, même une fois le plan validé."""
    client = make_client("awaiting_plan_validation")

    resp = client.post("/api/agents/a1/continue", json={"text": "Oui, ça part"})

    assert resp.status_code == 200
    assert client._calls == [("resume", "Oui, ça part")]


def test_question_libre_reprend_le_tour_en_pause(make_client):
    client = make_client("awaiting_input")

    resp = client.post("/api/agents/a1/continue", json={"text": "réponse A"})

    assert resp.status_code == 200
    assert client._calls == [("resume", "réponse A")]


def test_sans_question_pendante_c_est_un_tour_neuf(make_client):
    """Pas de pending sur disque : un message ordinaire ouvre bien un nouveau tour."""
    client = make_client("finished", pending_present=False)

    resp = client.post("/api/agents/a1/continue", json={"text": "et maintenant X"})

    assert resp.status_code == 200
    assert client._calls == [("continue", "et maintenant X")]


def test_remise_impossible_n_est_pas_annoncee_ok(make_client):
    """`_respawn` refuse de lancer un jumeau quand un process tourne déjà pour la session :
    la remise rend None, RIEN n'est parti. La route répondait quand même 200 {"ok": true} et
    la réponse de l'utilisateur disparaissait sans une trace. Elle doit désormais le DIRE."""
    client = make_client("awaiting_input", delivered=None)

    resp = client.post("/api/agents/a1/continue", json={"text": "ma réponse"})

    assert resp.status_code == 409
    body = resp.get_json()
    assert body["reason"] == "not_delivered"
    assert "n'a PAS été transmis" in body["error"]
