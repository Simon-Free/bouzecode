# [desc] Tests for the central extra-directory registry: registration, replacement, filtering, isolation. [/desc]
"""Tests for paths.py — central extra-dir registry."""
import sys
from pathlib import Path

import pytest

import bouzecode.backend.core.paths as _paths


@pytest.fixture(autouse=True)
def reset_extra_dirs():
    """Ensure extra dirs are clean between tests."""
    _paths._extra_dirs = []
    yield
    _paths._extra_dirs = []


def test_get_extra_dirs_empty_by_default():
    assert _paths.get_extra_dirs() == []


def test_register_and_get_extra_dirs(tmp_path):
    d1 = tmp_path / "one"
    d2 = tmp_path / "two"
    d1.mkdir()
    d2.mkdir()
    _paths.register_extra_dirs([str(d1), str(d2)])
    result = _paths.get_extra_dirs()
    assert len(result) == 2
    assert result[0] == d1.resolve()
    assert result[1] == d2.resolve()


def test_register_replaces_previous(tmp_path):
    d1 = tmp_path / "one"
    d2 = tmp_path / "two"
    d1.mkdir()
    d2.mkdir()
    _paths.register_extra_dirs([str(d1)])
    assert len(_paths.get_extra_dirs()) == 1
    _paths.register_extra_dirs([str(d2)])
    assert len(_paths.get_extra_dirs()) == 1
    assert _paths.get_extra_dirs()[0] == d2.resolve()


def test_register_filters_empty_strings():
    _paths.register_extra_dirs(["", None, ""])  # type: ignore
    assert _paths.get_extra_dirs() == []


def test_get_extra_dirs_returns_copy():
    _paths.register_extra_dirs(["."])
    dirs = _paths.get_extra_dirs()
    dirs.append(Path("/fake"))
    assert len(_paths.get_extra_dirs()) == 1
