# [desc] Pytest fixtures for readme_sync: a mini code tree and a subprocess CLI runner. [/desc]
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mini_tree(tmp_path: Path) -> Path:
    """A small real tree: pkg/ with code, pkg/sub/ with code, .venv/ to be ignored."""
    pkg = tmp_path / "pkg"
    sub = pkg / "sub"
    venv = tmp_path / ".venv"
    for d in (pkg, sub, venv):
        d.mkdir(parents=True)

    (pkg / "core.py").write_text(
        "def compute_total(x):\n    return x + 1\n\n\ndef _helper():\n    return 0\n",
        encoding="utf-8",
    )
    (pkg / "io_utils.py").write_text(
        "def read_rows(path):\n    return []\n", encoding="utf-8"
    )
    (sub / "widget.py").write_text(
        "class Widget:\n    def render(self):\n        return 'w'\n", encoding="utf-8"
    )
    (venv / "junk.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def run_cli():
    """Run the real CLI as a subprocess. Returns (returncode, stdout, stderr)."""
    def _run(*args: str) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, "-m", "readme_sync", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr
    return _run
