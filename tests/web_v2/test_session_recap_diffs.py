"""Verify GET /api/sessions/<key>/recap assembles + orders diffs server-side (T8).

Two scenarios played at the real HTTP endpoint:
  1. session WITH recap: diffs ordered by recap.changes, non-listed code files relegated
     to the end (alpha), test_*.py isolated at the very end (new tests then fixed tests).
  2. fallback session WITHOUT recap: diffs sorted alphabetically, recap=null.
No mocks: real Flask app, real session JSON on disk.
"""
from __future__ import annotations

import json

import pytest


def _snap(before: str, after: str, is_new: bool = False) -> dict:
    return {"before": before, "after": after, "is_new": is_new}


def _session_with_recap() -> dict:
    """changes order = b.py then a.py; z.py is a code file NOT in changes;
    two test files: test_new.py (new) and test_fixed.py (edited)."""
    return {
        "model": "claude-sonnet-4-20250514",
        "turn_count": 3,
        "close_reason": "final_answer",
        "saved_at": "2026-06-13T09:00:00",
        "recap": {
            "symptoms": "Bouton figé au clic",
            "explanation": "Le poller n'était pas reprogrammé",
            "tests": "2 tests verts",
            "changes": [
                {"file": "src/pkg/b.py", "summary": "ajout fonction handler"},
                {"file": "src/pkg/a.py", "summary": "appel du handler"},
            ],
        },
        "file_snapshots": {
            "src/pkg/a.py": _snap("old a\n", "new a\nmore a\n"),
            "src/pkg/b.py": _snap("", "brand new b\n", is_new=True),
            "src/pkg/z.py": _snap("old z\n", "new z\n"),
            "tests/test_new.py": _snap("", "def test_x():\n    assert True\n", is_new=True),
            "tests/test_fixed.py": _snap("def test_y():\n    assert 0\n",
                                         "def test_y():\n    assert 1\n"),
        },
    }


def _session_without_recap() -> dict:
    """No recap key at all (historical/crashed session)."""
    return {
        "model": "claude-sonnet-4-20250514",
        "turn_count": 1,
        "close_reason": "error",
        "saved_at": "2026-06-13T09:00:00",
        "file_snapshots": {
            "src/pkg/c.py": _snap("old c\n", "new c\n"),
            "src/pkg/a.py": _snap("old a\n", "new a\n"),
            "src/pkg/b.py": _snap("old b\n", "new b\n"),
        },
    }


def _write_session(tmp_path, monkeypatch, data: dict, name: str) -> str:
    from bouzecode.web_v2.services.sessions import store
    from bouzecode.web_v2.services.sessions.store import runner as _runner

    daily_dir = tmp_path / "daily"
    day_dir = daily_dir / "2026-06-13"
    day_dir.mkdir(parents=True, exist_ok=True)

    session_path = day_dir / name
    session_path.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(store, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(_runner, "list_agents", lambda: [])

    return f"daily/2026-06-13/{name}"


def _make_client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestRecapWithChanges:
    def test_diffs_ordered_by_changes_then_others_then_tests(self, tmp_path, monkeypatch):
        key = _write_session(tmp_path, monkeypatch, _session_with_recap(), "with_recap.json")
        client = _make_client()

        resp = client.get(f"/api/sessions/{key}/recap")
        assert resp.status_code == 200
        payload = json.loads(resp.get_data(as_text=True))

        # recap survives
        assert payload["recap"] is not None
        assert [c["file"] for c in payload["recap"]["changes"]] == ["src/pkg/b.py", "src/pkg/a.py"]

        files = [d["file"] for d in payload["diffs"]]
        # b.py then a.py (changes order), z.py (other code), then tests: new then fixed
        assert files == [
            "src/pkg/b.py",
            "src/pkg/a.py",
            "src/pkg/z.py",
            "tests/test_new.py",
            "tests/test_fixed.py",
        ]

    def test_tests_marked_is_test(self, tmp_path, monkeypatch):
        key = _write_session(tmp_path, monkeypatch, _session_with_recap(), "with_recap2.json")
        client = _make_client()
        payload = json.loads(client.get(f"/api/sessions/{key}/recap").get_data(as_text=True))

        by_file = {d["file"]: d for d in payload["diffs"]}
        assert by_file["tests/test_new.py"]["is_test"] is True
        assert by_file["tests/test_fixed.py"]["is_test"] is True
        assert by_file["src/pkg/a.py"]["is_test"] is False
        assert by_file["src/pkg/b.py"]["is_test"] is False

    def test_each_diff_has_raw_patch(self, tmp_path, monkeypatch):
        key = _write_session(tmp_path, monkeypatch, _session_with_recap(), "with_recap3.json")
        client = _make_client()
        payload = json.loads(client.get(f"/api/sessions/{key}/recap").get_data(as_text=True))

        a_entry = next(d for d in payload["diffs"] if d["file"] == "src/pkg/a.py")
        assert isinstance(a_entry["patch"], str)
        # unified diff of "old a" -> "new a\nmore a"
        assert "-old a" in a_entry["patch"]
        assert "+new a" in a_entry["patch"]


class TestRecapFallback:
    def test_no_recap_returns_null_and_alpha_diffs(self, tmp_path, monkeypatch):
        key = _write_session(tmp_path, monkeypatch, _session_without_recap(), "no_recap.json")
        client = _make_client()

        resp = client.get(f"/api/sessions/{key}/recap")
        assert resp.status_code == 200
        payload = json.loads(resp.get_data(as_text=True))

        assert payload["recap"] is None
        files = [d["file"] for d in payload["diffs"]]
        assert files == ["src/pkg/a.py", "src/pkg/b.py", "src/pkg/c.py"]
