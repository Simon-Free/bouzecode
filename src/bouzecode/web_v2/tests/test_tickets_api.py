# [desc] Tests for light ticket list, full list, single ticket detail endpoints, 404 handling, and JSON indentation. [/desc]
"""Vérifie les endpoints GET tickets liste light, ?full=1, zoom unitaire, 404, JSON indenté."""
from __future__ import annotations

import copy
import json

import pytest


FAKE_TICKETS = [
    {
        "id": "abc123",
        "title": "Fix parser bug",
        "prompt": "Please fix the parser bug in line 42 of parser.py",
        "created_at": "2026-06-10T10:00:00",
        "done": False,
        "typology": "bugfix",
        "comments": [
            {"at": "2026-06-10T11:00:00", "text": "Started working on it", "sent": True},
            {"at": "2026-06-10T12:00:00", "text": "Need clarification", "sent": False},
        ],
        "runs": [
            {
                "agent_id": "agent_001",
                "kind": "work",
                "model": "claude-sonnet",
                "started_at": "2026-06-10T10:05:00",
                "verdict": None,
                "state": "running",
            },
        ],
    },
    {
        "id": "def456",
        "title": "Add tests",
        "prompt": "Write unit tests for the new feature",
        "created_at": "2026-06-10T09:00:00",
        "done": True,
        "comments": [],
        "runs": [],
    },
]


@pytest.fixture()
def _patch_tickets(monkeypatch):
    """Patch ticket service functions to return fake data."""
    from bouzecode.web_v2.services.work import liveness, tickets

    def fake_list(slug, refresh=False, include_archived=False, **kwargs):
        if slug == "myproject":
            return FAKE_TICKETS
        return []

    def fake_get(slug, ticket_id):
        if slug == "myproject":
            # COPIE : la route de détail ré-attache l'état live des runs à la lecture ;
            # rendre le dict de module le ferait muter d'un test à l'autre.
            found = next((t for t in FAKE_TICKETS if t["id"] == ticket_id), None)
            return copy.deepcopy(found) if found else None
        return None

    def fake_derive_status(ticket, parents_with_children=None, liveness_state=""):
        """Double de `derive_status` : MÊME signature que la vraie (un `**kwargs` permissif
        masquerait une dérive de signature) et MÊME règle cardinale — une vivacité `crashed`
        ne peut jamais ressortir en statut de succès."""
        if liveness_state == "crashed":
            return "crashed"
        return "in_progress" if not ticket["done"] else "done"

    def fake_classify_ticket(ticket):
        """Vivacité DOUBLE, cohérente avec les faux runs. La vraie classification lit le
        disque (fichier agent + session) : ces tickets déclarent un run « running » sans
        aucun agent sur disque, elle les dirait donc « crashed » — alors que ces tests ne
        portent que sur la FORME du payload (light/full, JSON indenté)."""
        runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict)]
        return "running" if any(r.get("state") == "running" for r in runs) else "delivered"

    monkeypatch.setattr(tickets, "list_tickets", fake_list)
    monkeypatch.setattr(tickets, "get_ticket", fake_get)
    monkeypatch.setattr(tickets, "derive_status", fake_derive_status)
    monkeypatch.setattr(liveness, "classify_ticket", fake_classify_ticket)
    monkeypatch.setattr(tickets, "refresh_verdicts",
                        lambda slug, rows, **kwargs: None)  # aucun agent sur disque à lire

    # Patch _project_or_404 to accept "myproject"
    from bouzecode.web_v2.routes.work import tickets as tickets_routes
    monkeypatch.setattr(
        tickets_routes, "_project_or_404",
        lambda slug: ({"slug": slug, "name": "My Project"}, None) if slug == "myproject"
        else (None, ({"error": "not found"}, 404)),
    )


@pytest.fixture()
def client(_patch_tickets):
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --- L1: Light list ---

def test_list_light_no_prompt(client):
    """Light list must NOT include prompt or comment text."""
    resp = client.get("/api/projects/myproject/tickets")
    assert resp.status_code == 200
    data = resp.get_json()
    tickets = data["tickets"]
    assert len(tickets) == 2
    t1 = tickets[0]
    assert "prompt" not in t1
    assert "comments" not in t1  # no comments array in light mode


def test_list_light_fields(client):
    """Light list includes id, title, status, done, created_at, typology, runs summary, comments_count."""
    resp = client.get("/api/projects/myproject/tickets")
    data = resp.get_json()
    t1 = data["tickets"][0]
    assert t1["id"] == "abc123"
    assert t1["title"] == "Fix parser bug"
    assert t1["status"] == "in_progress"
    assert t1["done"] is False
    assert t1["created_at"] == "2026-06-10T10:00:00"
    assert t1["typology"] == "bugfix"
    assert t1["comments_count"] == 2
    # runs: only summary fields
    assert len(t1["runs"]) == 1
    run = t1["runs"][0]
    assert set(run.keys()) == {"agent_id", "kind", "model", "state", "verdict"}


def test_list_light_no_typology(client):
    """Ticket without typology should not have typology key (or None)."""
    resp = client.get("/api/projects/myproject/tickets")
    data = resp.get_json()
    t2 = data["tickets"][1]
    assert t2.get("typology") is None or "typology" not in t2


def test_list_light_comments_count_zero(client):
    """Ticket with no comments should have comments_count=0."""
    resp = client.get("/api/projects/myproject/tickets")
    data = resp.get_json()
    t2 = data["tickets"][1]
    assert t2["comments_count"] == 0


# --- L1: Full list (?full=1) ---

def test_list_full_has_prompt(client):
    """?full=1 returns full shape including prompt and comments."""
    resp = client.get("/api/projects/myproject/tickets?full=1")
    assert resp.status_code == 200
    data = resp.get_json()
    t1 = data["tickets"][0]
    assert t1["prompt"] == "Please fix the parser bug in line 42 of parser.py"
    assert "comments" in t1
    assert len(t1["comments"]) == 2
    assert t1["comments"][0]["text"] == "Started working on it"


# --- L2: Zoom unitaire ---

def test_zoom_ticket_found(client):
    """GET /api/tickets/<slug>/<id> returns full ticket detail."""
    resp = client.get("/api/tickets/myproject/abc123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == "abc123"
    assert data["prompt"] == "Please fix the parser bug in line 42 of parser.py"
    assert len(data["comments"]) == 2
    assert data["comments"][0]["text"] == "Started working on it"
    assert data["status"] == "in_progress"


def test_zoom_ticket_not_found(client):
    """GET /api/tickets/<slug>/<id> returns 404 for unknown ticket."""
    resp = client.get("/api/tickets/myproject/unknown999")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


# --- JSON indent ---

def test_list_json_indented(client):
    """List endpoint returns indented JSON."""
    resp = client.get("/api/projects/myproject/tickets")
    raw = resp.get_data(as_text=True)
    # Indented JSON has newlines and spaces
    assert "\n" in raw
    assert "  " in raw


def test_zoom_json_indented(client):
    """Zoom endpoint returns indented JSON."""
    resp = client.get("/api/tickets/myproject/abc123")
    raw = resp.get_data(as_text=True)
    assert "\n" in raw
    assert "  " in raw
