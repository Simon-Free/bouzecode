"""Deps editables relatives d'un worktree isolé : le lien vers le vrai dépôt sibling
rend `../dep` résoluble depuis le worktree (sinon uv sync casse, venv_ok=False)."""
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import worktree_sources


def _make_repo(root: Path, sources_toml: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='x'\nversion='0'\n\n[tool.uv.sources]\n" + sources_toml,
        encoding="utf-8")
    return root


def test_relative_editable_source_is_linked_to_real_dep(tmp_path):
    # Vrai layout : <workspace>/main_repo  +  <workspace>/dep_repo (le sibling réel)
    workspace = tmp_path / "workspace"
    dep = workspace / "dep_repo"
    dep.mkdir(parents=True)
    (dep / "MARKER.txt").write_text("real dep", encoding="utf-8")
    main = _make_repo(workspace / "main_repo", "dep = { path = '../dep_repo', editable = true }")

    # Worktree isolé, AILLEURS : ../dep_repo y pointe vers un sibling inexistant.
    worktree = _make_repo(tmp_path / "worktrees" / "main_repo" / "tk1",
                          "dep = { path = '../dep_repo', editable = true }")
    assert not (worktree / ".." / "dep_repo" / "MARKER.txt").exists()

    worktree_sources.link_editable_sources(worktree, str(main))

    linked = worktree / ".." / "dep_repo" / "MARKER.txt"
    assert linked.exists() and linked.read_text(encoding="utf-8") == "real dep"


def test_nested_relative_source_and_idempotent(tmp_path):
    workspace = tmp_path / "workspace"
    nested = workspace / "group" / "libdb"
    nested.mkdir(parents=True)
    (nested / "MARKER.txt").write_text("nested", encoding="utf-8")
    main = _make_repo(workspace / "main_repo",
                      "libdb = { path = '../group/libdb', editable = true }")
    worktree = _make_repo(tmp_path / "worktrees" / "main_repo" / "tk2",
                          "libdb = { path = '../group/libdb', editable = true }")

    worktree_sources.link_editable_sources(worktree, str(main))
    worktree_sources.link_editable_sources(worktree, str(main))  # 2e passe = no-op

    linked = worktree / ".." / "group" / "libdb" / "MARKER.txt"
    assert linked.read_text(encoding="utf-8") == "nested"


@pytest.mark.skipif(sys.platform != "win32", reason="jonctions Windows")
def test_stale_link_to_wrong_target_is_repointed(tmp_path):
    # Un run précédent a laissé un lien vers une MAUVAISE cible (cf. jonction périmée Windows).
    workspace = tmp_path / "workspace"
    good = workspace / "dep_repo"
    good.mkdir(parents=True)
    (good / "MARKER.txt").write_text("good", encoding="utf-8")
    wrong = tmp_path / "wrong_target"
    wrong.mkdir()
    (wrong / "MARKER.txt").write_text("wrong", encoding="utf-8")
    main = _make_repo(workspace / "main_repo", "dep = { path = '../dep_repo', editable = true }")
    worktree = _make_repo(tmp_path / "worktrees" / "main_repo" / "tk3",
                          "dep = { path = '../dep_repo', editable = true }")

    stale = worktree.parent / "dep_repo"
    stale.parent.mkdir(parents=True, exist_ok=True)
    # jonction (pas de privilège requis, contrairement au symlink) vers la MAUVAISE cible
    subprocess.run(["cmd", "/c", "mklink", "/J", str(stale), str(wrong)],
                   capture_output=True, check=True)
    worktree_sources.link_editable_sources(worktree, str(main))

    linked = worktree / ".." / "dep_repo" / "MARKER.txt"
    assert linked.read_text(encoding="utf-8") == "good"  # repointé vers la bonne cible
