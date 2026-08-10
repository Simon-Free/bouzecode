# [desc] End-to-end LLM test: fresh tree → rename → hook marks stale → --check fails → --regen → fresh again. [/desc]
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from readme_sync.hashing import read_lock
from readme_sync.regen import api_key
from readme_sync.tests._helpers import make_fresh

pytestmark = pytest.mark.llm

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "readme_sync", *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


def _fire_hook(file_path: Path) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    return subprocess.run(
        [sys.executable, "-m", "readme_sync.hook"],
        cwd=REPO_ROOT, input=json.dumps(payload), capture_output=True, text=True,
    )


def test_full_process_fresh_to_stale_to_regen_to_fresh(tmp_path: Path):
    if api_key() is None:
        pytest.skip("no API credentials")

    # --- arbre fresh : root + pkg (+ pkg/sub) tous documentés ---
    root = tmp_path
    pkg = root / "pkg"
    sub = pkg / "sub"
    sub.mkdir(parents=True)
    core = pkg / "core.py"
    core.write_text("def compute_total(x):\n    return x\n", encoding="utf-8")
    (sub / "widget.py").write_text("class Widget:\n    pass\n", encoding="utf-8")

    make_fresh(sub, "The widget sub-package.")
    make_fresh(pkg, "The core package.")
    make_fresh(root, "The tmp root.")

    r0 = _run_cli("--check", "--root", str(root))
    assert r0.returncode == 0, r0.stdout + r0.stderr

    # --- dev renomme la fonction ---
    core.write_text("def compute_grand_total(x):\n    return x\n", encoding="utf-8")

    # --- hook fire -> lock pkg stale ---
    h = _fire_hook(core)
    assert h.returncode == 0, h.stdout + h.stderr
    assert read_lock(pkg)["stale"] is True

    # --- --check rouge ---
    r1 = _run_cli("--check", "--root", str(root))
    assert r1.returncode == 1

    # --- --regen pkg (vrai LLM) ---
    rg = _run_cli("--regen", "pkg", "--root", str(root))
    assert rg.returncode == 0, rg.stdout + rg.stderr

    doc = (pkg / "AGENTS.md").read_text(encoding="utf-8")
    assert "compute_grand_total" in doc
    assert "compute_total(" not in doc

    # lock repassé fresh
    assert read_lock(pkg)["stale"] is False

    # --- --check vert ---
    r2 = _run_cli("--check", "--root", str(root))
    assert r2.returncode == 0, r2.stdout + r2.stderr
