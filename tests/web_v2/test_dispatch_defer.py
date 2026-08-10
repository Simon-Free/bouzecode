# [desc] BUG 1 : dispatch(defer=True) crée le ticket et répond AVANT le travail lourd
# (provisioning worktree + spawn), qui part en tâche de fond. Empêche le faux timeout
# du manager (→ tickets dupliqués). Fakes purs, zéro agent LLM, zéro git. [/desc]
from __future__ import annotations

import threading

from bouzecode.web_v2.services.work import dispatch
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import _persistence


class _FakeAgent:
    def __init__(self, agent_id="abc123def456"):
        self.agent_id = agent_id


def _wire(monkeypatch, tmp_path):
    """Route tout vers un projet factice, ticket dans un dossier temp, pas d'isolation."""
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    project = {"slug": "p", "name": "Projet", "path": str(tmp_path)}
    monkeypatch.setattr(dispatch.projects, "list_projects", lambda: [project])
    monkeypatch.setattr(dispatch.projects, "find", lambda slug: project)
    monkeypatch.setattr(dispatch, "get_typology", lambda name, path: {"profile": "", "default_model": ""})
    monkeypatch.setattr(dispatch, "resolve_isolation",
                        lambda path, requested, needs_worktree=False: ("shared", "test", ""))


def test_defer_returns_ticket_then_launches_in_background(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    launched = threading.Event()
    seen: list[str] = []

    def fake_launch(slug, ticket, project_path, profile, model, isolation="shared",
                    parent="", resume_branch="", work_branch=""):
        seen.append(ticket["id"])
        launched.set()

    monkeypatch.setattr(dispatch, "_launch", fake_launch)

    result = dispatch.dispatch("fais un truc", project_slug="p", typology="default",
                               parent="mgr123456789", defer=True)

    # La réponse est immédiate : routée, avec ticket_id, marquée deferred, SANS 'key'.
    assert result["routed"] is True
    assert result["ticket_id"]
    assert result["deferred"] is True
    assert "key" not in result
    # Le launch lourd s'exécute bien en tâche de fond, sur CE ticket.
    assert launched.wait(3)
    assert seen == [result["ticket_id"]]


def test_deferred_ticket_persisted_before_launch(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    # launch qui bloque : prouve que le ticket existe AVANT que le launch ait fini.
    gate = threading.Event()
    monkeypatch.setattr(dispatch, "_launch", lambda *a: gate.wait(3))

    result = dispatch.dispatch("bosse", project_slug="p", typology="default",
                               parent="mgr123456789", defer=True)

    stored = tickets_svc.get_ticket("p", result["ticket_id"])
    assert stored is not None
    assert stored["parent"] == "mgr123456789"
    gate.set()


def test_sync_dispatch_still_returns_key(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    monkeypatch.setattr(dispatch.runner, "create_agent",
                        lambda *a, **k: _FakeAgent("abc123def456"))

    result = dispatch.dispatch("bosse", project_slug="p", typology="default")

    assert result.get("deferred") is not True  # absent en mode synchrone
    assert result["key"] == "agent/abc123def456"
    # un run 'work' a été enregistré sur le ticket
    stored = tickets_svc.get_ticket("p", result["ticket_id"])
    assert stored["runs"][0]["kind"] == "work"


def test_launch_bg_swallows_no_error_but_logs(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)

    def boom(*a):
        raise RuntimeError("provider env manquant")

    monkeypatch.setattr(dispatch, "_launch", boom)
    # _launch_bg ne doit PAS propager (thread daemon) mais ne pas planter non plus.
    dispatch._launch_bg("p", {"id": "x"}, str(tmp_path), "", "", "shared", "mgr")
