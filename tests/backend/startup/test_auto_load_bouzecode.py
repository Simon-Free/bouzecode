# [desc] Test that .bouzecode/ directory in cwd is auto-detected and registered in extra_dirs at startup. [/desc]
"""Test that .bouzecode/ in cwd is auto-loaded at startup."""
import os
import tempfile
from pathlib import Path

import bouzecode.backend.core.paths as paths
from bouzecode.backend.core.paths import get_extra_dirs, add_extra_dir, register_extra_dirs


def _reset_extra_dirs():
    paths._extra_dirs = []


def test_auto_detect_bouzecode_in_cwd():
    """When cwd has .bouzecode/, the unified code adds it via register_extra_dirs."""
    _reset_extra_dirs()
    original_cwd = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    try:
        bouzecode_dir = Path(tmpdir) / ".bouzecode"
        bouzecode_dir.mkdir()
        os.chdir(tmpdir)

        # Simulate the unified bouzecode.py logic
        extra_dirs = []
        if os.path.isdir(".bouzecode"):
            extra_dirs.append(os.path.abspath(".bouzecode"))
        register_extra_dirs(extra_dirs)

        dirs = get_extra_dirs()
        assert len(dirs) == 1
        assert dirs[0] == bouzecode_dir.resolve()
    finally:
        os.chdir(original_cwd)
        _reset_extra_dirs()


def test_no_bouzecode_dir_no_auto_add():
    """When cwd has no .bouzecode/, nothing is registered."""
    _reset_extra_dirs()
    original_cwd = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    try:
        os.chdir(tmpdir)

        extra_dirs = []
        if os.path.isdir(".bouzecode"):
            extra_dirs.append(os.path.abspath(".bouzecode"))
        if extra_dirs:
            register_extra_dirs(extra_dirs)

        dirs = get_extra_dirs()
        assert len(dirs) == 0
    finally:
        os.chdir(original_cwd)
        _reset_extra_dirs()


def test_no_duplicate_with_explicit_extra_dir():
    """When --extra-dir and auto-detect resolve to the same path, register_extra_dirs deduplicates."""
    _reset_extra_dirs()
    original_cwd = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    try:
        bouzecode_dir = Path(tmpdir) / ".bouzecode"
        bouzecode_dir.mkdir()
        os.chdir(tmpdir)

        # Simulate unified code: both explicit and auto-detect produce the same path
        extra_dirs = [str(bouzecode_dir), os.path.abspath(".bouzecode")]
        register_extra_dirs(extra_dirs)

        dirs = get_extra_dirs()
        assert len(dirs) == 1, f"Expected 1 (deduped) but got {len(dirs)}: {dirs}"
        assert dirs[0] == bouzecode_dir.resolve()
    finally:
        os.chdir(original_cwd)
        _reset_extra_dirs()
