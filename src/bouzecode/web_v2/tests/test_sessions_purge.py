# [desc] Tests pytest de la purge sûre des conversations de test: heuristique is_test_session + endpoints purge-test (dry/soft-delete) et restore [/desc]
"""Pas de unittest.mock : fakes purs + monkeypatch pytest.

- ``is_test_session`` teste en direct (fonction pure).
- Endpoints via le vrai test_client Flask ; ``store.list_sessions`` remplacee
  par une liste de rows controlee (fake pur) et ``purge.DELETED_PATH`` pointe
  vers un fichier temporaire isole.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.sessions import purge, store


# ------------------------------------------------------------------ heuristique
@pytest.mark.parametrize(
    "title,turns,expected",
    [
        ("test typology", 2, True),
        ("test ping", 1, True),
        ("Test Ping", 3, True),          # insensible casse, borne turns
        ("test typology", 20, False),    # trop de tours -> vraie session
        ("Corrige le bug X", 1, False),  # pas 'test'
        ("testament budget", 1, False),  # word-boundary : 'testament' != 'test'
        ("", 1, False),                  # titre vide
    ],
)
def test_is_test_session(title, turns, expected):
    assert purge.is_test_session(title, turns) is expected


# ------------------------------------------------------------------ fixtures
FAKE_ROWS = {
    "agents": [
        {"key": "agent/aaaaaa", "title": "test typology", "turn_count": 2},
        {"key": "agent/bbbbbb", "title": "Refonte facturation", "turn_count": 14},
    ],
    "days": [
        {
            "date": "2026-07-01",
            "sessions": [
                {"key": "daily/2026-07-01/session_x.json", "title": "test ping", "turn_count": 1},
                {"key": "daily/2026-07-01/session_y.json", "title": "Audit securite", "turn_count": 9},
            ],
        }
    ],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    monkeypatch.setattr(store, "list_sessions", lambda: FAKE_ROWS)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ------------------------------------------------------------------ endpoints
def test_purge_dry_run_lists_candidates_without_deleting(client):
    resp = client.post("/api/sessions/purge-test", json={"dry": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["dry"] is True
    keys = {c["key"] for c in data["candidates"]}
    assert keys == {"agent/aaaaaa", "daily/2026-07-01/session_x.json"}
    # aucune vraie conversation dans les candidats
    assert "agent/bbbbbb" not in keys
    assert "daily/2026-07-01/session_y.json" not in keys
    # dry-run n'ecrit rien
    assert purge.load_deleted() == {}


def test_purge_soft_deletes_and_excludes(client):
    resp = client.post("/api/sessions/purge-test", json={"dry": False})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["dry"] is False
    purged = {c["key"] for c in data["purged"]}
    assert purged == {"agent/aaaaaa", "daily/2026-07-01/session_x.json"}
    # registre persiste les clefs soft-deleted
    deleted = purge.load_deleted()
    assert set(deleted) == purged
    # apres purge, elles ne sont plus detectees comme candidates
    assert purge.detect_test_sessions() == []


def test_real_conversation_never_purged(client):
    client.post("/api/sessions/purge-test", json={"dry": False})
    deleted = purge.load_deleted()
    assert "agent/bbbbbb" not in deleted
    assert "daily/2026-07-01/session_y.json" not in deleted


def test_restore_endpoint_reverts_soft_delete(client):
    client.post("/api/sessions/purge-test", json={"dry": False})
    assert purge.is_deleted("agent/aaaaaa") is True
    resp = client.post("/api/sessions/agent/aaaaaa/restore")
    assert resp.status_code == 200
    assert resp.get_json().get("ok") is True
    assert purge.is_deleted("agent/aaaaaa") is False
    # redevient candidate apres restore
    keys = {c["key"] for c in purge.detect_test_sessions()}
    assert "agent/aaaaaa" in keys
