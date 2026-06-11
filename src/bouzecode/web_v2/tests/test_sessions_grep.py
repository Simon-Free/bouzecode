# [desc] Tests for GET /api/sessions/grep endpoint: regex search, filters (day/role), invalid regex, limit. [/desc]
"""Vérifie la recherche transversale dans les sessions via le test client Flask."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def _fake_sessions(tmp_path, monkeypatch):
    """Create fake daily sessions and patch store to find them."""
    from bouzecode.web_v2.services.sessions import store

    daily_dir = tmp_path / "daily"
    day1 = daily_dir / "2026-06-10"
    day1.mkdir(parents=True)
    day2 = daily_dir / "2026-06-09"
    day2.mkdir(parents=True)

    session1 = {
        "model": "claude-sonnet",
        "messages": [
            {"role": "user", "content": "Bonjour le monde"},
            {"role": "assistant", "content": "Salut! Comment ça va?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"name": "Read", "input": json.dumps({"file_path": "/tmp/foo.py"})}
                ],
            },
        ],
    }
    session2 = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Fix the bug in parser.py"},
            {"role": "tool", "content": "Error: syntax error line 42", "name": "Bash"},
        ],
    }
    (day1 / "session_abc.json").write_text(json.dumps(session1), encoding="utf-8")
    (day2 / "session_def.json").write_text(json.dumps(session2), encoding="utf-8")

    monkeypatch.setattr(store, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "cache.json")

    # Patch runner.list_agents to return empty (no web agents)
    from bouzecode.web_v2.services.sessions.store import runner as _runner
    monkeypatch.setattr(_runner, "list_agents", lambda: [])


@pytest.fixture()
def client(_fake_sessions):
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_grep_simple_match(client):
    resp = client.get("/api/sessions/grep?q=Bonjour")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["scanned"] >= 1
    assert len(data["matches"]) >= 1
    match = data["matches"][0]
    assert match["role"] == "user"
    assert "Bonjour" in match["excerpt"]
    assert match["key"].startswith("daily/2026-06-10/")


def test_grep_tool_call_content(client):
    """Search matches inside tool_calls input."""
    resp = client.get("/api/sessions/grep?q=foo\\.py")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["matches"]) >= 1
    assert data["matches"][0]["role"] == "assistant"


def test_grep_filter_day(client):
    resp = client.get("/api/sessions/grep?q=.&day=2026-06-09")
    assert resp.status_code == 200
    data = resp.get_json()
    keys = {m["key"] for m in data["matches"]}
    assert all("2026-06-09" in k for k in keys)


def test_grep_filter_role(client):
    resp = client.get("/api/sessions/grep?q=.&role=tool")
    assert resp.status_code == 200
    data = resp.get_json()
    assert all(m["role"] == "tool" for m in data["matches"])


def test_grep_invalid_regex(client):
    resp = client.get("/api/sessions/grep?q=[invalid")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "regex invalide" in data["error"]


def test_grep_missing_q(client):
    resp = client.get("/api/sessions/grep")
    assert resp.status_code == 400


def test_grep_limit_respected(client):
    resp = client.get("/api/sessions/grep?q=.&limit=2")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["matches"]) <= 2
