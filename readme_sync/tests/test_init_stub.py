from __future__ import annotations

from pathlib import Path

from readme_sync import contract
from readme_sync.bootstrap import bootstrap_readme_map
from readme_sync.hashing import read_lock
from readme_sync.propagate import create_root_map

from ._helpers import make_fresh


class _StubBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _StubResp:
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]


class _StubMessages:
    def __init__(self, owner: "_StubClient") -> None:
        self._owner = owner

    def create(self, *, model, max_tokens, system, messages):
        self._owner.calls += 1
        # A canonical, contract-valid README carrying a symbol name.
        readme = (
            "# folder/\n\n"
            "This folder does something useful.\n\n"
            "## Module Reference\n\n"
            "| File | Lines | Purpose |\n"
            "|------|-------|---------|\n"
            "| mod.py | 3 | `foo` computes things |\n"
        )
        return _StubResp(readme)


class _StubClient:
    """Hand-written stub: no unittest.mock. Records how many LLM calls happen."""

    def __init__(self) -> None:
        self.calls = 0
        self.messages = _StubMessages(self)


def _make_tree(root: Path) -> None:
    pkg = root / "pkg"
    sub = pkg / "sub"
    sub.mkdir(parents=True)
    (pkg / "core.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (sub / "widget.py").write_text("def bar():\n    return 2\n", encoding="utf-8")


def test_init_with_stub_generates_readmes_and_root_map(tmp_path):
    _make_tree(tmp_path)
    stub = _StubClient()

    report = bootstrap_readme_map(tmp_path, client=stub)

    assert report["disabled"] is False
    assert report["first_launch"] is True

    # A README per code folder, each contract-valid with the symbol present.
    for rel in ("pkg", "pkg/sub"):
        readme = tmp_path / rel / "AGENTS.md"
        assert readme.exists(), rel
        md = readme.read_text(encoding="utf-8")
        assert contract.validate(md) == []
        assert "## Module Reference" in md
        assert "foo" in md
        assert read_lock(tmp_path / rel) is not None

    # The ROOT AGENTS.md is a map listing the code folders.
    root_md = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Subfolders" in root_md
    assert "[pkg/](pkg/AGENTS.md)" in root_md
    # Root is a pure map, not a module doc.
    assert "## Module Reference" not in root_md

    # Two code folders => exactly two LLM calls (root map is zero-LLM).
    assert stub.calls == 2


def test_launch_gate_on_by_default_opt_out_with_zero(tmp_path, monkeypatch):
    """maybe_bootstrap_readme runs by default; BOUZECODE_README_SYNC=0 opts out."""
    from readme_sync.bootstrap import maybe_bootstrap_readme

    monkeypatch.delenv("BOUZECODE_README_SYNC", raising=False)
    assert maybe_bootstrap_readme(tmp_path)["disabled"] is False

    monkeypatch.setenv("BOUZECODE_README_SYNC", "0")
    assert maybe_bootstrap_readme(tmp_path)["disabled"] is True


def test_bootstrap_skipped_in_linked_worktree(tmp_path):
    """Throwaway ticket worktrees (`.git` is a file) are never auto-documented."""
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / ".git").write_text(
        "gitdir: /repo/.git/worktrees/ticket\n", encoding="utf-8"
    )

    stub = _StubClient()
    report = bootstrap_readme_map(tmp_path, client=stub)

    assert report["skipped"] == "worktree"
    assert stub.calls == 0
    assert not (d / "AGENTS.md").exists()


def test_bootstrap_skipped_when_too_many_folders(tmp_path):
    """A project at/over the folder cap is not auto-documented (no LLM calls)."""
    for i in range(3):
        d = tmp_path / f"pkg{i}"
        d.mkdir()
        (d / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    stub = _StubClient()
    report = bootstrap_readme_map(tmp_path, client=stub, max_folders=2)

    assert report["skipped"] == "too_many_folders"
    assert report["folders"] >= 2
    assert stub.calls == 0
    assert not (tmp_path / "pkg0" / "AGENTS.md").exists()


def test_recheck_regens_only_changed(tmp_path):
    _make_tree(tmp_path)
    pkg = tmp_path / "pkg"
    sub = pkg / "sub"
    # Prime everything fresh (README + lock) WITHOUT any LLM call.
    make_fresh(pkg, "The pkg package.")
    make_fresh(sub, "The sub package.")
    create_root_map(tmp_path)  # root map now present -> next run is a recheck

    # Change ONE file in pkg so only pkg's hash manifest drifts.
    (pkg / "core.py").write_text("def foo():\n    return 42\n", encoding="utf-8")

    stub = _StubClient()
    report = bootstrap_readme_map(tmp_path, client=stub)

    assert report["disabled"] is False
    assert report["first_launch"] is False
    # ONLY pkg was regenerated; sub stayed fresh -> stub called exactly once.
    assert stub.calls == 1
    assert report["regenerated"] == [str(pkg.resolve())]
