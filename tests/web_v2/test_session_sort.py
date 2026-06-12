"""Test that list_sessions sorts by last activity (saved_at) not creation time."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def daily_dir(tmp_path):
    """Create a fake daily dir with sessions having different saved_at."""
    day_dir = tmp_path / "2026-06-10"
    day_dir.mkdir(parents=True)

    # Session created early but active recently
    early_created_active = day_dir / "session_000100_aaaa.json"
    early_created_active.write_text(json.dumps({
        "first_message": "early created but recently active",
        "model": "claude-opus-4-6",
        "turn_count": 5,
        "saved_at": "2026-06-10T16:00:00",
    }), encoding="utf-8")

    # Session created late but inactive
    late_created_inactive = day_dir / "session_230000_bbbb.json"
    late_created_inactive.write_text(json.dumps({
        "first_message": "late created but inactive",
        "model": "claude-opus-4-6",
        "turn_count": 1,
        "saved_at": "2026-06-10T10:00:00",
    }), encoding="utf-8")

    # Session created mid-day, most recently active
    mid_created_most_active = day_dir / "session_120000_cccc.json"
    mid_created_most_active.write_text(json.dumps({
        "first_message": "mid created most recently active",
        "model": "claude-opus-4-6",
        "turn_count": 10,
        "saved_at": "2026-06-10T16:25:00",
    }), encoding="utf-8")

    return tmp_path


def test_sessions_sorted_by_saved_at(daily_dir):
    """Sessions within a day should be sorted by saved_at descending."""
    from bouzecode.web_v2.services.sessions.store import list_sessions, DAILY_DIR

    with patch("bouzecode.web_v2.services.sessions.store.DAILY_DIR", daily_dir), \
         patch("bouzecode.web_v2.services.sessions.store.runner") as mock_runner, \
         patch("bouzecode.web_v2.services.sessions.store._load_cache", return_value={}), \
         patch("bouzecode.web_v2.services.sessions.store._save_cache"):
        mock_runner.list_agents.return_value = []
        result = list_sessions()

    days = result["days"]
    assert len(days) == 1
    sessions = days[0]["sessions"]
    assert len(sessions) == 3

    # Most recently active first
    assert "mid created most recently active" in sessions[0]["title"]
    assert "early created but recently active" in sessions[1]["title"]
    assert "late created but inactive" in sessions[2]["title"]
