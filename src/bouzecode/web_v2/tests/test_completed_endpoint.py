# [desc] Tests for POST /api/tickets/<slug>/<id>/completed: advances the workflow for the completing agent. [/desc]
"""L'endpoint /completed (notifié par le hook on_completion) avance la machine à états
du ticket via workflow.advance, en traitant l'agent qui a fini comme terminé.

No unittest.mock — fakes purs + pytest.monkeypatch."""
from __future__ import annotations

import pytest

FAKE = {"id": "tk1", "title": "T", "prompt": "p",
        "worktree": {"state": "provisioned", "worktree": "/wt"},
        "runs": [{"agent_id": "coder1", "kind": "work", "verdict": None, "state": "running"}]}


@pytest.fixture()
def client(monkeypatch):
    from bouzecode.web_v2.services.work import tickets, workflow
    from bouzecode.web_v2.routes.work import tickets as routes

    seen = {"refresh": [], "advance": []}

    def fake_get(slug, ticket_id):
        return FAKE if (slug == "proj" and ticket_id == FAKE["id"]) else None

    def fake_refresh(slug, rows, done_agent="", persist=True, agents_index=None):
        seen["refresh"].append((slug, [t["id"] for t in rows], done_agent))

    def fake_advance(slug, ticket, done_agent=""):
        seen["advance"].append((slug, ticket["id"], done_agent))
        return "validating"

    def fake_mark_completed(slug, ticket, agent_id):
        seen.setdefault("completed", []).append((slug, ticket["id"], agent_id))

    monkeypatch.setattr(tickets, "get_ticket", fake_get)
    monkeypatch.setattr(tickets, "refresh_verdicts", fake_refresh)
    monkeypatch.setattr(tickets, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(workflow, "advance", fake_advance)
    monkeypatch.setattr(routes, "_project_or_404",
                        lambda slug: ({"slug": slug, "name": "P"}, None) if slug == "proj"
                        else (None, ({"error": "nope"}, 404)))

    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c._seen = seen  # type: ignore[attr-defined]
        yield c


def test_completed_advances_workflow(client):
    resp = client.post("/api/tickets/proj/tk1/completed", json={"agent_id": "coder1"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "advanced_to": "validating"}
    # workflow advanced for THIS ticket, with the completing agent passed through.
    assert client._seen["advance"] == [("proj", "tk1", "coder1")]
    # le rafraîchissement porte sur CE seul ticket et traite l'agent qui a fini comme terminé.
    assert client._seen["refresh"] == [("proj", ["tk1"], "coder1")]
    # the run was marked completed (crash-vs-graceful marker for the watchdog).
    assert client._seen["completed"] == [("proj", "tk1", "coder1")]


def test_completed_deferred_close_does_not_advance(client):
    """A `final_answer_deferred` close must NOT advance the workflow: its queued checks
    (e.g. an Azure deploy) run AFTER the process exits, and advancing here would
    validate/merge before the deploy. The reconciler advances once the drain deletes
    <session>.deferred.json."""
    resp = client.post("/api/tickets/proj/tk1/completed",
                       json={"agent_id": "coder1", "close_reason": "final_answer_deferred"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "advanced_to": None, "deferred": True}
    assert client._seen["advance"] == []                 # never advanced prematurely
    assert client._seen.get("completed", []) == []       # never marked completed here


def test_completed_unknown_ticket_404(client):
    resp = client.post("/api/tickets/proj/nope/completed", json={"agent_id": "x"})
    assert resp.status_code == 404
    assert client._seen["advance"] == []


def test_completed_unknown_project_404(client):
    resp = client.post("/api/tickets/other/tk1/completed", json={"agent_id": "x"})
    assert resp.status_code == 404
