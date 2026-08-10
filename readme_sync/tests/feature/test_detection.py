# [desc] Feature tests for readme_sync --check/--list-stale: detects MISSING/STALE/ORPHAN folders, ignores .venv. [/desc]
from __future__ import annotations

from pathlib import Path

from readme_sync.hashing import git_ignored_paths, iter_code_folders
from readme_sync.tests._helpers import make_fresh


def _stale_lines(run_cli, root: Path) -> list[str]:
    code, out, err = run_cli("--list-stale", "--root", str(root))
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def test_dev_sees_all_folders_missing_on_virgin_tree(mini_tree, run_cli):
    code, out, err = run_cli("--check", "--root", str(mini_tree))
    assert code == 1, err
    assert "[MISSING] pkg" in out
    assert "sub" in out
    assert ".venv" not in out


def test_fresh_tree_is_silent(mini_tree, run_cli):
    make_fresh(mini_tree / "pkg")
    make_fresh(mini_tree / "pkg" / "sub")
    code, out, err = run_cli("--check", "--root", str(mini_tree))
    assert code == 0, out + err


def test_editing_a_file_makes_folder_stale(mini_tree, run_cli):
    make_fresh(mini_tree / "pkg")
    make_fresh(mini_tree / "pkg" / "sub")
    (mini_tree / "pkg" / "core.py").write_text(
        "def compute_total(x):\n    return x + 2\n", encoding="utf-8"
    )
    stale = _stale_lines(run_cli, mini_tree)
    assert "pkg" in stale
    assert str(Path("pkg") / "sub") not in stale


def test_new_code_file_flags_stale(mini_tree, run_cli):
    make_fresh(mini_tree / "pkg")
    make_fresh(mini_tree / "pkg" / "sub")
    (mini_tree / "pkg" / "new_mod.py").write_text("x = 1\n", encoding="utf-8")
    assert "pkg" in _stale_lines(run_cli, mini_tree)


def test_deleted_file_flags_stale(mini_tree, run_cli):
    make_fresh(mini_tree / "pkg")
    make_fresh(mini_tree / "pkg" / "sub")
    (mini_tree / "pkg" / "io_utils.py").unlink()
    assert "pkg" in _stale_lines(run_cli, mini_tree)


def test_folder_emptied_of_code_is_orphan(mini_tree, run_cli):
    make_fresh(mini_tree / "pkg")
    make_fresh(mini_tree / "pkg" / "sub")
    (mini_tree / "pkg" / "sub" / "widget.py").unlink()
    code, out, err = run_cli("--check", "--root", str(mini_tree))
    assert "[ORPHAN]" in out
    assert "sub" in out


def test_ignore_list_never_reported(mini_tree, run_cli):
    make_fresh(mini_tree / "pkg")
    make_fresh(mini_tree / "pkg" / "sub")
    code, out, err = run_cli("--check", "--root", str(mini_tree))
    assert ".venv" not in out
    stale = _stale_lines(run_cli, mini_tree)
    assert not any(".venv" in s for s in stale)


def _names(root: Path) -> set[str]:
    return {p.name for p in iter_code_folders(root)}


def test_virtualenv_excluded_by_pyvenv_cfg(tmp_path):
    """A venv is skipped by its pyvenv.cfg marker, whatever it is named."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "m.py").write_text("x = 1\n", encoding="utf-8")
    venv = tmp_path / "weird-env"
    (venv / "lib" / "vendored").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (venv / "lib" / "vendored" / "dep.py").write_text("y = 2\n", encoding="utf-8")
    names = _names(tmp_path)
    assert "pkg" in names
    assert "weird-env" not in names
    assert "vendored" not in names


def test_gitignored_dir_excluded(tmp_path):
    """A directory matched by .gitignore is not scanned."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    (tmp_path / ".gitignore").write_text("generated/\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "auto.py").write_text("z = 3\n", encoding="utf-8")
    assert (tmp_path / "generated").resolve() in git_ignored_paths(tmp_path)
    names = _names(tmp_path)
    assert "pkg" in names
    assert "generated" not in names
