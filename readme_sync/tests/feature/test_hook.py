# [desc] Feature tests for readme_sync PostToolUse hook: marks lock stale on code edits, no-op on AGENTS.md/non-code. [/desc]
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from readme_sync.hashing import read_lock
from readme_sync.tests._helpers import make_fresh

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_hook(file_path: Path) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    return subprocess.run(
        [sys.executable, "-m", "readme_sync.hook"],
        input=json.dumps(payload),
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_editing_code_marks_lock_stale(mini_tree):
    pkg = mini_tree / "pkg"
    make_fresh(pkg)
    assert read_lock(pkg)["stale"] is False

    result = _run_hook(pkg / "core.py")
    assert result.returncode == 0

    assert read_lock(pkg)["stale"] is True


def test_editing_agents_md_itself_is_noop(mini_tree):
    pkg = mini_tree / "pkg"
    make_fresh(pkg)

    _run_hook(pkg / "AGENTS.md")

    assert read_lock(pkg)["stale"] is False


def test_editing_non_code_is_noop(mini_tree):
    pkg = mini_tree / "pkg"
    make_fresh(pkg)
    (pkg / "notes.txt").write_text("some notes", encoding="utf-8")

    _run_hook(pkg / "notes.txt")

    assert read_lock(pkg)["stale"] is False


def test_hook_creates_lock_if_missing(mini_tree):
    pkg = mini_tree / "pkg"
    (pkg / "AGENTS.md").write_text("# pkg/\n\nx\n\n## Module Reference\n", encoding="utf-8")
    lock = pkg / ".agents.lock"
    if lock.exists():
        lock.unlink()
    assert not lock.exists()

    result = _run_hook(pkg / "core.py")
    assert result.returncode == 0

    assert lock.exists()
    assert read_lock(pkg)["stale"] is True
