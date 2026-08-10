# [desc] Mechanical (LLM-free) tests that child README purposes propagate into parent Subfolders map tables. [/desc]
from __future__ import annotations

import re
from pathlib import Path

from readme_sync.contract import purpose_of
from readme_sync.hashing import code_files, iter_code_folders
from readme_sync.propagate import propagate_up, refresh_parent
from readme_sync.tests._helpers import make_fresh


def _build_tree(root: Path) -> None:
    """A real code tree: root/ has pkg_a/ and pkg_b/; pkg_a/ has sub/."""
    (root / "root_mod.py").write_text("def root_fn():\n    return 1\n", encoding="utf-8")

    pkg_a = root / "pkg_a"
    pkg_a.mkdir()
    (pkg_a / "a_mod.py").write_text("def a_fn():\n    return 2\n", encoding="utf-8")

    sub = pkg_a / "sub"
    sub.mkdir()
    (sub / "s_mod.py").write_text("def s_fn():\n    return 3\n", encoding="utf-8")

    pkg_b = root / "pkg_b"
    pkg_b.mkdir()
    (pkg_b / "b_mod.py").write_text("def b_fn():\n    return 4\n", encoding="utf-8")


def _make_all_fresh(root: Path) -> None:
    make_fresh(root, "The repository root.")
    make_fresh(root / "pkg_a", "Package A does A things.")
    make_fresh(root / "pkg_a" / "sub", "Subpackage of A.")
    make_fresh(root / "pkg_b", "Package B does B things.")


def _iter_readme_dirs(root: Path):
    for folder in iter_code_folders(root):
        if (folder / "AGENTS.md").exists():
            yield folder


def _subfolder_links(md: str) -> list[str]:
    """Extract the AGENTS.md link targets from a ## Subfolders table."""
    links = []
    in_section = False
    for line in md.splitlines():
        if line.strip() == "## Subfolders":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            for m in re.finditer(r"\]\(([^)]+)\)", line):
                links.append(m.group(1))
    return links


def test_child_purpose_propagates_to_parent_row(tmp_path):
    root = tmp_path
    _build_tree(root)
    _make_all_fresh(root)

    # Change pkg_a/sub's purpose, then propagate upward.
    sub = root / "pkg_a" / "sub"
    make_fresh(sub, "Brand new purpose for sub.")
    propagate_up(sub, root)

    pkg_a_md = (root / "pkg_a" / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Subfolders" in pkg_a_md
    assert "Brand new purpose for sub." in pkg_a_md
    assert "[sub/](sub/AGENTS.md)" in pkg_a_md


def test_map_has_no_dead_links(tmp_path):
    root = tmp_path
    _build_tree(root)
    _make_all_fresh(root)
    # Refresh every parent so tables are populated.
    for folder in _iter_readme_dirs(root):
        refresh_parent(folder)

    for folder in _iter_readme_dirs(root):
        md = (folder / "AGENTS.md").read_text(encoding="utf-8")
        for link in _subfolder_links(md):
            target = (folder / link).resolve()
            assert target.exists(), f"dead link {link} in {folder}"


def test_every_code_folder_reachable_from_root(tmp_path):
    root = tmp_path
    _build_tree(root)
    _make_all_fresh(root)
    for folder in _iter_readme_dirs(root):
        refresh_parent(folder)

    # BFS from root README following Subfolders links.
    reached = {root.resolve()}
    stack = [root.resolve()]
    while stack:
        cur = stack.pop()
        md = (cur / "AGENTS.md").read_text(encoding="utf-8")
        for link in _subfolder_links(md):
            child = (cur / link).resolve().parent
            if child not in reached:
                reached.add(child)
                stack.append(child)

    all_code_folders = {
        f.resolve() for f in iter_code_folders(root) if code_files(f)
    }
    assert all_code_folders <= reached, (
        f"unreachable: {all_code_folders - reached}"
    )


def test_root_readme_lists_all_top_level_packages(tmp_path):
    root = tmp_path
    _build_tree(root)
    _make_all_fresh(root)
    refresh_parent(root)

    root_md = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "[pkg_a/](pkg_a/AGENTS.md)" in root_md
    assert "[pkg_b/](pkg_b/AGENTS.md)" in root_md
    # And the purposes are mirrored from the children.
    assert "Package A does A things." in root_md
    assert "Package B does B things." in root_md
