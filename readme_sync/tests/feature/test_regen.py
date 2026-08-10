# [desc] Live-LLM tests (@pytest.mark.llm) validating regen_folder produces valid README structure, clears stale flag, reflects code changes, and only regenerates stale folders. [/desc]
from __future__ import annotations

from pathlib import Path

import pytest

from readme_sync.contract import validate
from readme_sync.hashing import read_lock, write_lock
from readme_sync.regen import api_key, regen_folder

pytestmark = pytest.mark.llm


def _require_llm():
    if api_key() is None:
        pytest.skip("no ANTHROPIC credentials in env — live-LLM test skipped")


def _read_doc(folder: Path) -> str:
    return (folder / "AGENTS.md").read_text(encoding="utf-8")


def test_regen_missing_readme_produces_valid_structure(mini_tree: Path):
    _require_llm()
    pkg = mini_tree / "pkg"
    assert not (pkg / "AGENTS.md").exists()

    regen_folder(pkg, mini_tree)

    doc = _read_doc(pkg)
    assert validate(doc) == []
    assert "compute_total" in doc


def test_regen_clears_stale_flag(mini_tree: Path, run_cli):
    _require_llm()
    from readme_sync.tests._helpers import make_fresh

    pkg = mini_tree / "pkg"
    make_fresh(pkg / "sub")  # so the only attention-needing folder is pkg
    # Pose a fresh AGENTS.md+lock, then make it stale by editing code.
    (pkg / "AGENTS.md").write_text(
        "# pkg/\n\nOld purpose.\n\n## Module Reference\n\n"
        "| File | Lines | Purpose |\n|------|-------|---------|\n",
        encoding="utf-8",
    )
    write_lock(pkg, stale=False)
    (pkg / "core.py").write_text(
        "def compute_total(x):\n    return x + 42\n", encoding="utf-8"
    )

    regen_folder(pkg, mini_tree)

    lock = read_lock(pkg)
    assert lock is not None
    assert lock.get("stale") is False

    code, _out, _err = run_cli("--check", "--root", str(mini_tree))
    assert code == 0


def test_regen_reflects_the_actual_change(mini_tree: Path):
    _require_llm()
    pkg = mini_tree / "pkg"
    (pkg / "core.py").write_text(
        "def compute_grand_total(x):\n    return x + 1\n", encoding="utf-8"
    )
    (pkg / "io_utils.py").unlink()  # keep the prompt small/focused

    regen_folder(pkg, mini_tree)

    doc = _read_doc(pkg)
    assert "compute_grand_total" in doc
    assert "compute_total(" not in doc


def test_regen_only_calls_llm_for_stale_folders(mini_tree: Path, run_cli, tmp_path: Path):
    _require_llm()
    from readme_sync.tests._helpers import make_fresh

    # pkg is stale (no README/lock at all -> MISSING is also flagged);
    # give it a fresh lock then dirty it so it is STALE, and make the others FRESH.
    pkg = mini_tree / "pkg"
    sub = pkg / "sub"

    make_fresh(sub)  # pkg/sub -> FRESH
    # two extra fresh code folders
    for name in ("alpha", "beta"):
        d = mini_tree / name
        d.mkdir()
        (d / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        make_fresh(d)

    # pkg: fresh then dirtied -> STALE
    make_fresh(pkg)
    (pkg / "core.py").write_text(
        "def compute_total(x):\n    return x + 99\n", encoding="utf-8"
    )

    code, out, _err = run_cli("--regen", "--root", str(mini_tree))
    assert code == 0
    regenerated = [ln for ln in out.splitlines() if ln.strip().startswith("regenerated")]
    assert len(regenerated) == 1, out
    assert "pkg" in regenerated[0]
