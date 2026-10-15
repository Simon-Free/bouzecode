# [desc] BUG 1 : la création d'un ticket (defer, le défaut) répond AVANT le travail lourd
# (provisioning worktree + spawn), qui part en tâche de fond. Empêche le faux timeout
# du manager (→ tickets dupliqués). Fakes purs, zéro agent LLM, zéro git. [/desc]
from __future__ import annotations

import threading

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.services.work import dispatch, projects
from bouzecode.web_v2.services.work.api_tickets import creation
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.runtime.runner import agent_creation


class _FakeAgent:
    def __init__(self, agent_id="abc123def456"):
        self.agent_id = agent_id


def _wire(monkeypatch, tmp_path):
    """Route tout vers un projet factice (pas un dépôt git : isolation `shared`), ticket dans un
    dossier temp, environnement API réputé joignable."""
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    project = {"slug": "p", "name": "Projet", "path": str(tmp_path)}
    monkeypatch.setattr(projects, "list_projects", lambda: [project])
    monkeypatch.setattr(projects, "find", lambda slug: project)
    monkeypatch.setattr(dispatch, "get_typology", lambda name, path: {"profile": "", "default_model": ""})
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)


def _creer(prompt: str, defer: bool) -> dict:
    """Ce que fait l'outil Agent d'un manager : POST /api/projects/p/tickets (service)."""
    return creation.creer("p", {"title": prompt, "prompt": prompt, "isolation": "shared",
                                "parent": "mgr123456789", "defer": defer})


def test_defer_returns_ticket_then_launches_in_background(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    launched = threading.Event()
    seen: list[str] = []

    def fake_launch(slug, ticket, project_path, profile, model, isolation="shared",
                    parent="", resume_branch="", work_branch=""):
        seen.append(ticket["id"])
        launched.set()

    monkeypatch.setattr(dispatch, "_launch", fake_launch)

    result = _creer("fais un truc", defer=True)

    # La réponse est immédiate : le ticket, en préparation, SANS 'key' (l'agent n'est pas né).
    assert result["ticket_id"] and result["state"] == "provisioning"
    assert "key" not in result
    # Le launch lourd s'exécute bien en tâche de fond, sur CE ticket.
    assert launched.wait(3)
    assert seen == [result["ticket_id"]]


def test_deferred_ticket_persisted_before_launch(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    # launch qui bloque : prouve que le ticket existe AVANT que le launch ait fini.
    gate = threading.Event()
    monkeypatch.setattr(dispatch, "_launch", lambda *a: gate.wait(3))

    result = _creer("bosse", defer=True)

    stored = tickets_svc.get_ticket("p", result["ticket_id"])
    assert stored is not None
    assert stored["parent"] == "mgr123456789"
    gate.set()


def test_sync_dispatch_still_returns_key(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    monkeypatch.setattr(agent_creation, "create_agent",
                        lambda *a, **k: _FakeAgent("abc123def456"))

    result = _creer("bosse", defer=False)

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
