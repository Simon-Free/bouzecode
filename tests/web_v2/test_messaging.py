# [desc] Service messaging : resolve_ticket retrouve (slug, ticket) sur disque (None sinon),
# send_to_ticket_agent (adaptateur de LA remise unique `api_tickets.remise`) met le message dans
# la file d'un enfant en plein tour, ou relance un agent au repos. Zéro agent LLM. [/desc]
from __future__ import annotations

from bouzecode.web_v2.services.work import messaging
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_processus, agent_reprise


def _wire_projects(monkeypatch, tmp_path, slugs=("p",)):
    projects = [{"slug": s, "name": s, "path": str(tmp_path)} for s in slugs]
    monkeypatch.setattr(messaging.projects, "list_projects", lambda: projects)


def test_resolve_ticket_finds_slug_and_ticket(monkeypatch, tmp_path):
    _wire_projects(monkeypatch, tmp_path, slugs=("a", "p"))
    created = tickets_svc.create_ticket("p", "titre", "prompt")

    resolved = messaging.resolve_ticket(created["id"])

    assert resolved is not None
    slug, ticket = resolved
    assert slug == "p"
    assert ticket["id"] == created["id"]


def test_resolve_ticket_absent_returns_none(monkeypatch, tmp_path):
    _wire_projects(monkeypatch, tmp_path)
    assert messaging.resolve_ticket("deadbeef") is None
    assert messaging.resolve_ticket("") is None


class _FakeAgent:
    agent_id = "a1"
    session_path = "/nope/session.json"
    ticket_slug = "p"

    def __init__(self, ticket_id: str = ""):
        self.ticket_id = ticket_id


def _ticket_lance(titre: str = "t") -> dict:
    """Un vrai ticket du store dont le run de travail est l'agent `a1`."""
    ticket = tickets_svc.create_ticket("p", titre, "prompt")
    tickets_svc.set_launching("p", ticket)
    tickets_svc.add_run("p", ticket, "a1", "work", "")
    return tickets_svc.get_ticket("p", ticket["id"])


def _commentaires(ticket: dict) -> list[tuple[str, bool]]:
    relu = tickets_svc.get_ticket("p", ticket["id"])
    return [(c["text"], c["sent"]) for c in relu.get("comments") or []]


def test_un_enfant_en_plein_tour_recoit_le_message_a_sa_prochaine_etape(monkeypatch):
    """Plus de 409 « attends la fin du tour » : le message part dans la file de l'enfant (sa
    boîte) — par LA remise unique (`api_tickets.remise`) ; `interrompre` coupe le tour."""
    from bouzecode.web_v2.services.work.api_tickets import remise
    ticket = _ticket_lance()
    interrompus = []
    monkeypatch.setattr(agent_fiche, "load_agent", lambda aid: _FakeAgent(ticket["id"]))
    monkeypatch.setattr(remise.store, "agent_status", lambda agent: {"state": "running"})
    monkeypatch.setattr(remise.file_messages, "mettre_en_file",
                        lambda agent_id, texte, origine="": {"id": "q1", "position": 1,
                                                             "boite": True, "text": texte})
    monkeypatch.setattr(remise.interruption, "interrompre",
                        lambda agent: interrompus.append(agent.agent_id) or {"ok": True})

    result = messaging.send_to_ticket_agent("p", ticket, "continue plutôt comme ça",
                                            interrompre=True)

    assert result["queued"] is True and result["delivered"] is False
    assert result["queue_id"] == "q1" and result["en_tour"] is True
    assert interrompus == ["a1"]
    assert _commentaires(ticket)[-1] == ("continue plutôt comme ça", True)


def test_send_without_work_run_is_409(monkeypatch):
    ticket = {"id": "t2", "runs": [], "comments": []}
    result = messaging.send_to_ticket_agent("p", ticket, "hello")
    assert result["ok"] is False
    assert result["code"] == 409 and result["reason"] == "pas_d_agent"


def test_send_relaunches_reaped_ticket(monkeypatch, tmp_path):
    """Ticket mergé (worktree nettoyé/reaped) → la remise NE refuse PAS : elle re-home vers un
    worktree frais (rehome_agent_cwd/reisolate) PUIS relance l'agent et journalise le
    commentaire — un follow-up doit relancer le travail, pas renvoyer une erreur."""
    from bouzecode.web_v2.services.work.api_tickets import remise
    ticket = _ticket_lance()
    calls: dict = {}
    monkeypatch.setattr(agent_fiche, "load_agent", lambda aid: _FakeAgent(ticket["id"]))
    monkeypatch.setattr(agent_processus, "session_process_running", lambda path: False)
    monkeypatch.setattr(remise.store, "agent_status", lambda agent: {"state": "finished"})
    monkeypatch.setattr(remise.pending, "exists", lambda path: False)
    monkeypatch.setattr(remise.dispatch, "rehome_agent_cwd",
                        lambda agent: calls.setdefault("rehome", True) or "/fresh/wt")
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda agent, text: calls.setdefault("continue", text))

    result = messaging.send_to_ticket_agent("p", ticket, "fais X")

    assert result == {"ok": True, "delivered": True, "queued": False}
    assert calls["rehome"] is True  # re-home AVANT relance
    assert calls["continue"] == "fais X"  # relance effective
    assert _commentaires(ticket)[-1] == ("fais X", True)  # commentaire journalisé


def test_send_continues_finished_agent(monkeypatch, tmp_path):
    from bouzecode.web_v2.services.work.api_tickets import remise
    ticket = _ticket_lance()
    calls: dict = {}
    monkeypatch.setattr(agent_fiche, "load_agent", lambda aid: _FakeAgent(ticket["id"]))
    monkeypatch.setattr(agent_processus, "session_process_running", lambda path: False)
    monkeypatch.setattr(remise.store, "agent_status", lambda agent: {"state": "finished"})
    monkeypatch.setattr(remise.pending, "exists", lambda path: False)
    monkeypatch.setattr(remise.dispatch, "rehome_agent_cwd", lambda agent: "/fresh/wt")
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda agent, text: calls.setdefault("continue", text))

    result = messaging.send_to_ticket_agent("p", ticket, "fais X")

    assert result == {"ok": True, "delivered": True, "queued": False}
    assert calls["continue"] == "fais X"
    assert _commentaires(ticket)[-1] == ("fais X", True)
