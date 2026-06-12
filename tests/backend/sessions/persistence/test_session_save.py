# [desc] Tests atomic JSON write safety and backup rotation for session persistence [/desc]
"""Tests for atomic, interrupt-safe session save utilities."""
import json
from pathlib import Path

import pytest

from bouzecode.backend.commands.session import _safe_write_json, _rotate_backup


def test_safe_write_json_creates_file(tmp_path):
    target = tmp_path / "test.json"
    _safe_write_json(target, {"key": "value"}, indent=2)
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"key": "value"}


def test_safe_write_json_overwrites_atomically(tmp_path):
    target = tmp_path / "test.json"
    _safe_write_json(target, {"version": 1})
    _safe_write_json(target, {"version": 2})
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert not target.with_suffix(".tmp").exists()


def test_safe_write_json_creates_parent_dirs(tmp_path):
    target = tmp_path / "sub" / "dir" / "test.json"
    _safe_write_json(target, {"nested": True})
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["nested"] is True


def test_safe_write_json_preserves_original_on_serialization_error(tmp_path):
    target = tmp_path / "test.json"
    _safe_write_json(target, {"good": True})
    circular = {}
    circular["self"] = circular
    with pytest.raises((ValueError, TypeError)):
        _safe_write_json(target, circular)
    assert json.loads(target.read_text(encoding="utf-8")) == {"good": True}
    assert not target.with_suffix(".tmp").exists()


def test_safe_write_json_no_tmp_leftover(tmp_path):
    target = tmp_path / "out.json"
    _safe_write_json(target, [1, 2, 3])
    assert not (tmp_path / "out.tmp").exists()


def test_rotate_backup_creates_bak(tmp_path):
    target = tmp_path / "session_latest.json"
    target.write_text('{"old": true}', encoding="utf-8")
    _rotate_backup(target)
    bak = target.with_suffix(".bak.json")
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8")) == {"old": True}


def test_rotate_backup_overwrites_previous_bak(tmp_path):
    target = tmp_path / "session.json"
    target.write_text('{"v": 1}', encoding="utf-8")
    _rotate_backup(target)
    target.write_text('{"v": 2}', encoding="utf-8")
    _rotate_backup(target)
    bak = target.with_suffix(".bak.json")
    assert json.loads(bak.read_text(encoding="utf-8")) == {"v": 2}


def test_rotate_backup_noop_if_no_file(tmp_path):
    target = tmp_path / "nonexistent.json"
    _rotate_backup(target)
    assert not target.with_suffix(".bak.json").exists()


def test_safe_write_json_unicode_content(tmp_path):
    target = tmp_path / "unicode.json"
    _safe_write_json(target, {"emoji": "hello", "accent": "bouzecode"})
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["accent"] == "bouzecode"
