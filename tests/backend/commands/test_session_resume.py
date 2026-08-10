# [desc] Tests for /resume interactive picker: lists recent sessions newest-first, pages to older ones, restores the picked session. [/desc]
"""Drives cmd_resume with a fake input feed (no mocking lib, just monkeypatch + a tmp DAILY_DIR)."""
import json
import os
import types
from pathlib import Path

import pytest

from bouzecode.backend.commands.session import session_pick, session_resume


def _make_session(day_dir: Path, ts: str, sid: str, first_msg: str, mtime: float) -> Path:
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"session_{ts}_{sid}.json"
    data = {
        "session_id": sid,
        "saved_at": f"2026-06-25 {ts[:2]}:{ts[2:4]}:{ts[4:]}",
        "first_message": first_msg,
        "turn_count": 3,
        "messages": [{"role": "user", "content": first_msg}],
        "context_state": {"notes": {}},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _patch_daily(monkeypatch, daily: Path):
    from bouzecode.backend.core import config
    monkeypatch.setattr(config, "DAILY_DIR", daily, raising=False)


def _feed_inputs(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))
    # cmd_history needs a fully-fledged state; we only care about the load here.
    monkeypatch.setattr(session_resume, "cmd_history", lambda *a, **k: None)


def test_collect_recent_sessions_newest_first(tmp_path, monkeypatch):
    daily = tmp_path / "daily"
    _make_session(daily / "2026-06-24", "100000", "aaa", "old", mtime=100.0)
    _make_session(daily / "2026-06-25", "100000", "bbb", "new", mtime=200.0)
    _patch_daily(monkeypatch, daily)

    found = session_pick.collect_recent_sessions()
    assert [p.parent.name for p in found] == ["2026-06-25", "2026-06-24"]


def test_resume_picks_session(tmp_path, monkeypatch):
    daily = tmp_path / "daily"
    _make_session(daily / "2026-06-24", "090000", "old1", "older task", mtime=100.0)
    newest = _make_session(daily / "2026-06-25", "110000", "new1", "newest task", mtime=300.0)
    _patch_daily(monkeypatch, daily)
    _feed_inputs(monkeypatch, ["1"])

    state = types.SimpleNamespace()
    session_resume.cmd_resume("", state, {})
    assert state.messages == [{"role": "user", "content": "newest task"}]


def test_resume_paging_then_pick(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-06-25"
    # 12 sessions -> first page shows 10, "m" reveals the rest, then pick #11 (an older one).
    paths = [_make_session(daily, f"1000{i:02d}", f"s{i:02d}", f"task {i}", mtime=1000.0 - i)
             for i in range(12)]
    _patch_daily(monkeypatch, daily.parent)
    _feed_inputs(monkeypatch, ["m", "11"])

    state = types.SimpleNamespace()
    session_resume.cmd_resume("", state, {})
    # newest-first: index 10 (1-based 11) is the 11th-newest = task 10.
    assert state.messages == [{"role": "user", "content": "task 10"}]


def test_resume_out_of_range_before_paging(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-06-25"
    for i in range(12):
        _make_session(daily, f"1000{i:02d}", f"s{i:02d}", f"task {i}", mtime=1000.0 - i)
    _patch_daily(monkeypatch, daily.parent)
    _feed_inputs(monkeypatch, ["11"])  # only 10 shown on the first page -> rejected

    state = types.SimpleNamespace()
    session_resume.cmd_resume("", state, {})
    assert not hasattr(state, "messages")
