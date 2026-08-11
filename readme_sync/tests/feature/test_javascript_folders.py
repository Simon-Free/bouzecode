# [desc] Feature tests: a JavaScript folder is a code folder, and vendored trees are ignored. [/desc]
"""A folder of hand-written `.js` is documented like a folder of `.py`.

A front-end folder holds its logic in `.js`; treating only `.py` as code made
`--check` call such a folder ORPHAN ("map with no code") and let it drift with
nothing to catch it. Third-party code shipped in-tree (`vendor/`) stays out:
it is not ours to document.
"""
from __future__ import annotations

from pathlib import Path

from readme_sync.hashing import classify, code_files, iter_code_folders
from readme_sync.states import FolderState
from readme_sync.tests._helpers import make_fresh


def _js_tree(tmp_path: Path) -> Path:
    """A front-end folder, plus a vendored bundle that must stay invisible."""
    web = tmp_path / "web"
    vendored = web / "vendor" / "editor"
    for d in (web, vendored):
        d.mkdir(parents=True)
    (web / "panel.js").write_text(
        "export function renderPanel(node) {\n  return node;\n}\n", encoding="utf-8"
    )
    (vendored / "bundle.js").write_text("var x=1;\n", encoding="utf-8")
    return tmp_path


def test_js_folder_without_a_map_is_missing(tmp_path):
    root = _js_tree(tmp_path)
    assert classify(root / "web").state == FolderState.MISSING


def test_js_folder_with_a_map_is_not_an_orphan(tmp_path):
    root = _js_tree(tmp_path)
    make_fresh(root / "web")
    assert classify(root / "web").state == FolderState.FRESH


def test_editing_a_js_file_flags_the_folder_stale(tmp_path):
    root = _js_tree(tmp_path)
    make_fresh(root / "web")
    (root / "web" / "panel.js").write_text(
        "export function renderPanel(node) {\n  return node.parentNode;\n}\n",
        encoding="utf-8",
    )
    status = classify(root / "web")
    assert status.state == FolderState.STALE
    assert any("panel.js" in reason for reason in status.reasons)


def test_vendored_code_is_neither_walked_nor_counted(tmp_path):
    root = _js_tree(tmp_path)
    walked = {p.name for p in iter_code_folders(root)}
    assert "editor" not in walked
    assert "vendor" not in walked
    assert [p.name for p in code_files(root / "web")] == ["panel.js"]
