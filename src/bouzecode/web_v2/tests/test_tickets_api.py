# [desc] Tests for light ticket list, full list, single ticket detail endpoints, 404 handling, and JSON indentation — lus sur le vrai store, l'état servi est `ticket.state`. [/desc]
"""Vérifie les endpoints GET tickets liste light, ?full=1, zoom unitaire, 404, JSON indenté."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import projet, run, semer

SLUG = "myproject"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app
    projet(tmp_path, monkeypatch, SLUG)
    semer(SLUG, "abc123", etats.RUNNING, title="Fix parser bug",
          prompt="Please fix the parser bug in line 42 of parser.py", typology="bugfix",
          comments=[{"at": "2026-06-10T11:00:00", "text": "Started working on it", "sent": True},
                    {"at": "2026-06-10T12:00:00", "text": "Need clarification", "sent": False}],
          runs=[run("agent_001", state="running", model="claude-sonnet")])
    semer(SLUG, "def456", etats.CLOSED, "accepte", title="Add tests",
          prompt="Write unit tests for the new feature")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _par_id(resp) -> dict:
    return {t["id"]: t for t in resp.get_json()["tickets"]}


# --- Liste légère ---

def test_list_light_no_prompt(client):
    """Light list must NOT include prompt or comment text."""
    resp = client.get(f"/api/projects/{SLUG}/tickets")
    assert resp.status_code == 200
    tickets = _par_id(resp)
    assert len(tickets) == 2
    assert "prompt" not in tickets["abc123"] and "comments" not in tickets["abc123"]


def test_list_light_fields(client):
    """id, title, state + projection du lexique, created_at, typology, runs résumés, comments_count."""
    t1 = _par_id(client.get(f"/api/projects/{SLUG}/tickets"))["abc123"]
    assert t1["title"] == "Fix parser bug"
    assert (t1["state"], t1["status"], t1["libelle_statut"]) == (etats.RUNNING, "en cours",
                                                                 "En cours")
    assert t1["typology"] == "bugfix"
    assert t1["comments_count"] == 2
    assert t1["version"] >= 1
    [resume] = t1["runs"]
    assert set(resume) == {"agent_id", "kind", "model", "state"}
    assert resume["state"] == "running"


def test_list_light_no_typology(client):
    t2 = _par_id(client.get(f"/api/projects/{SLUG}/tickets"))["def456"]
    assert t2.get("typology") is None


def test_list_light_comments_count_zero(client):
    t2 = _par_id(client.get(f"/api/projects/{SLUG}/tickets"))["def456"]
    assert t2["comments_count"] == 0 and t2["status"] == "terminé"


# --- Liste complète (?full=1) ---

def test_list_full_has_prompt(client):
    t1 = _par_id(client.get(f"/api/projects/{SLUG}/tickets?full=1"))["abc123"]
    assert t1["prompt"] == "Please fix the parser bug in line 42 of parser.py"
    assert len(t1["comments"]) == 2
    assert t1["comments"][0]["text"] == "Started working on it"
    assert t1["state"] == etats.RUNNING


# --- Zoom unitaire ---

def test_zoom_ticket_found(client):
    resp = client.get(f"/api/projects/{SLUG}/tickets/abc123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == "abc123"
    assert data["prompt"] == "Please fix the parser bug in line 42 of parser.py"
    assert len(data["comments"]) == 2
    assert (data["state"], data["status"]) == (etats.RUNNING, "en cours")
    assert data["runs"][0]["agent_id"] == "agent_001"


def test_zoom_ticket_not_found(client):
    resp = client.get(f"/api/projects/{SLUG}/tickets/unknown999")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


# --- JSON indenté ---

def test_list_json_indented(client):
    raw = client.get(f"/api/projects/{SLUG}/tickets").get_data(as_text=True)
    assert "\n" in raw and "  " in raw


def test_zoom_json_indented(client):
    raw = client.get(f"/api/projects/{SLUG}/tickets/abc123").get_data(as_text=True)
    assert "\n" in raw and "  " in raw


def test_une_lecture_ne_change_rien(client):
    """B1 : lire dix fois la liste et la fiche ne touche pas au store (version inchangée)."""
    from bouzecode.web_v2.services.work import tickets
    avant = tickets.get_ticket(SLUG, "abc123")["version"]
    for _ in range(10):
        client.get(f"/api/projects/{SLUG}/tickets")
        client.get(f"/api/projects/{SLUG}/tickets/abc123")
    assert tickets.get_ticket(SLUG, "abc123")["version"] == avant
