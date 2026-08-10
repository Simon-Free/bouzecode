# [desc] Service messaging : resolve_ticket retrouve (slug, ticket) sur disque (None sinon),
# send_to_ticket_agent refuse (409) tant que l'agent tourne. Fakes purs, zéro agent LLM. [/desc]
from __future__ import annotations

from bouzecode.web_v2.services.work import messaging
from bouzecode.web_v2.services.work import tickets as tickets_svc


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
    session_path = "/nope/session.json"


def test_send_refuses_while_agent_running(monkeypatch):
    ticket = {"id": "t1", "runs": [{"kind": "work", "agent_id": "a1"}], "comments": []}
    monkeypatch.setattr(messaging.runner, "load_agent", lambda aid: _FakeAgent())
    monkeypatch.setattr(messaging.store, "agent_status", lambda agent: {"state": "running"})

    result = messaging.send_to_ticket_agent("p", ticket, "continue plutôt comme ça")

    assert result["ok"] is False
    assert result["code"] == 409
    assert "tourne encore" in result["error"]


def test_send_without_work_run_is_409(monkeypatch):
    ticket = {"id": "t2", "runs": [], "comments": []}
    result = messaging.send_to_ticket_agent("p", ticket, "hello")
    assert result["ok"] is False
    assert result["code"] == 409


def test_send_relaunches_reaped_ticket(monkeypatch, tmp_path):
    """Ticket mergé (worktree nettoyé/reaped) → send_to_ticket_agent NE refuse PLUS : il re-home
    vers un worktree frais (rehome_agent_cwd/reisolate) PUIS relance l'agent et journalise le
    commentaire — un follow-up doit relancer le travail, pas renvoyer une erreur."""
    ticket = {"id": "t9", "title": "t", "runs": [{"kind": "work", "agent_id": "a1"}],
              "comments": [], "reaped": True,
              "worktree": {"state": "cleaned"}}
    calls: dict = {}
    monkeypatch.setattr(messaging.runner, "load_agent", lambda aid: _FakeAgent())
    monkeypatch.setattr(messaging.store, "agent_status", lambda agent: {"state": "finished"})
    monkeypatch.setattr(messaging.pending, "exists", lambda path: False)
    monkeypatch.setattr(messaging.dispatch, "rehome_agent_cwd",
                        lambda agent: calls.setdefault("rehome", True) or "/fresh/wt")
    monkeypatch.setattr(messaging.runner, "continue_agent",
                        lambda agent, text: calls.setdefault("continue", text))

    result = messaging.send_to_ticket_agent("p", ticket, "fais X")

    assert result == {"ok": True}
    assert calls["rehome"] is True  # re-home AVANT relance
    assert calls["continue"] == "fais X"  # relance effective
    assert ticket["comments"][-1]["text"] == "fais X"  # commentaire journalisé


def test_send_continues_finished_agent(monkeypatch, tmp_path):
    ticket = {"id": "t3", "title": "t", "runs": [{"kind": "work", "agent_id": "a1"}],
              "comments": []}
    calls: dict = {}
    monkeypatch.setattr(messaging.runner, "load_agent", lambda aid: _FakeAgent())
    monkeypatch.setattr(messaging.store, "agent_status", lambda agent: {"state": "finished"})
    monkeypatch.setattr(messaging.pending, "exists", lambda path: False)
    monkeypatch.setattr(messaging.dispatch, "rehome_agent_cwd", lambda agent: "/fresh/wt")
    monkeypatch.setattr(messaging.runner, "continue_agent",
                        lambda agent, text: calls.setdefault("continue", text))

    result = messaging.send_to_ticket_agent("p", ticket, "fais X")

    assert result == {"ok": True}
    assert calls["continue"] == "fais X"
    assert ticket["comments"][-1]["text"] == "fais X"
    assert ticket["comments"][-1]["sent"] is True
