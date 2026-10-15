# [desc] Repondre a un agent en pause CHAUDE (question posee, pas de pending.json). [/desc]
"""Un agent qui pose une question SANS mourir (pause chaude : process resident du warm
pool, IPC `awaiting_input`, `answer.txt` sonde) n'ecrit AUCUN `<session>.pending.json`
-- ce fichier n'est produit que par la pause froide. Les deux chemins de reponse
(`…/tickets/<id>/messages` du Bureau et `/api/agents/<id>/messages` des conversations)
doivent donc aiguiller sur l'ETAT et non sur la presence du fichier, sinon la reponse
part en `continue_agent` -> `_respawn` refuse (pid vivant) -> 409 `not_delivered`.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.runtime import pending
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_reprise
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import delivery, dispatch, messaging, tickets


def _agent():
    return agent_fiche.Agent(agent_id="a1", prompt="p", model="", cwd="/live", pid=4242,
                        started_at="", session_path="/tmp/a1.session.json")


def _ticket():
    return {"id": "T1", "runs": [{"kind": "work", "agent_id": "a1"}]}


@pytest.fixture()
def pause_chaude(monkeypatch):
    """Agent en `awaiting_input` avec pending.json ABSENT (pause chaude), et toutes les
    ecritures de bord neutralisees. Renvoie la liste des remises effectuees."""
    calls: list[tuple[str, str]] = []
    agent = _agent()
    monkeypatch.setattr(agent_fiche, "load_agent", lambda aid: agent if aid == "a1" else None)
    monkeypatch.setattr(store, "agent_status", lambda a: {"state": "awaiting_input"})
    monkeypatch.setattr(store, "invalidate_status", lambda aid: None)
    monkeypatch.setattr(pending, "exists", lambda sp: False)
    monkeypatch.setattr(dispatch, "rehome_agent_cwd",
                        lambda a: calls.append(("rehome", "")) or a.cwd)
    monkeypatch.setattr(delivery, "reopen_for_new_work", lambda slug, tid: None)
    monkeypatch.setattr(tickets, "add_comment", lambda slug, ticket, text, human: None)
    monkeypatch.setattr(agent_reprise, "resume_pending_agent",
                        lambda a, text: calls.append(("resume", text)) or agent)
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda a, text: calls.append(("continue", text)) or agent)
    return calls


def test_le_bureau_livre_sa_reponse_a_un_agent_en_pause_chaude(pause_chaude):
    """Chemin du chatbot /bureau : send_to_ticket_agent."""
    result = messaging.send_to_ticket_agent("bouzecode", _ticket(), "option A")
    assert result["ok"] is True, result
    assert ("resume", "option A") in pause_chaude, pause_chaude
    assert ("continue", "option A") not in pause_chaude
    # Et on ne reisole PAS le worktree sous un process vivant.
    assert ("rehome", "") not in pause_chaude


def test_la_route_des_messages_livre_aussi_a_un_agent_en_pause_chaude(pause_chaude):
    """Chemin /conversations : POST /api/agents/<id>/messages."""
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    reponse = client.post("/api/agents/a1/messages", json={"mode": "refuse", "text": "option A"})
    assert reponse.status_code == 200, reponse.get_data(as_text=True)
    assert ("resume", "option A") in pause_chaude, pause_chaude
    assert ("continue", "option A") not in pause_chaude
