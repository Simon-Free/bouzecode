# [desc] CLI tests verifying --check exit codes (1 stale / 0 fresh) and --list-stale prints only bare paths. [/desc]
from __future__ import annotations

from pathlib import Path

from readme_sync.tests._helpers import make_fresh


def test_check_exit_1_when_stale(mini_tree, run_cli):
    code, out, err = run_cli("--check", "--root", str(mini_tree))
    assert code == 1


def test_check_exit_0_when_fresh(mini_tree, run_cli):
    make_fresh(mini_tree / "pkg")
    make_fresh(mini_tree / "pkg" / "sub")
    code, out, err = run_cli("--check", "--root", str(mini_tree))
    assert code == 0, out + err


def test_list_stale_prints_only_paths(mini_tree, run_cli):
    code, out, err = run_cli("--list-stale", "--root", str(mini_tree))
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    assert lines, "expected at least one stale path"
    for ln in lines:
        assert not ln.startswith("["), f"unexpected decorated line: {ln}"
        assert "readme_sync" not in ln or Path(ln).parts, ln
