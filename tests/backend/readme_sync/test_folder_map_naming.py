# [desc] The folder-map filename is a setting: default README.md, overridable, and --check works on a clean clone. [/desc]
"""`python -m readme_sync --check` must work on a clone of THIS repository.

It did not: the tool looked for `AGENTS.md`, a file this repo deliberately does
not ship, so every folder came back MISSING — including the root. The filename
is now a setting (readme_sync/naming.py) defaulting to `README.md`, and a folder
map without its generated lock sidecar is UNLOCKED (informational) rather than
STALE, because a fresh clone has no lock and nothing proves the map drifted.
"""
from __future__ import annotations

import pytest

from readme_sync import naming
from readme_sync.hashing import classify, scan
from readme_sync.states import FolderState


@pytest.fixture(autouse=True)
def restore_active_naming():
    previous = naming.active()
    yield
    naming.use(previous)


@pytest.fixture
def documented_package(tmp_path):
    """A code folder carrying a hand-written map, with no lock sidecar."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text("def go():\n    return 1\n", encoding="utf-8")
    (pkg / "README.md").write_text(
        "# pkg/\n\nDoes the thing.\n\n## Module Reference\n", encoding="utf-8"
    )
    return pkg


def test_the_default_map_file_is_readme_md():
    naming.use(None)
    assert naming.resolve_naming(root=None).doc_name == "README.md"


def test_the_lock_sidecar_follows_the_map_name():
    assert naming.lock_name_for("README.md") == ".readme.lock"
    assert naming.lock_name_for("AGENTS.md") == ".agents.lock"


def test_pyproject_can_ask_for_another_name(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.readme_sync]\ndoc_name = "AGENTS.md"\n', encoding="utf-8"
    )
    resolved = naming.resolve_naming(tmp_path)
    assert resolved.doc_name == "AGENTS.md"
    assert resolved.lock_name == ".agents.lock"


def test_the_environment_outranks_pyproject(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.readme_sync]\ndoc_name = "AGENTS.md"\n', encoding="utf-8"
    )
    monkeypatch.setenv(naming.ENV_DOC_NAME, "MAP.md")
    assert naming.resolve_naming(tmp_path).doc_name == "MAP.md"


def test_an_explicit_name_outranks_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(naming.ENV_DOC_NAME, "MAP.md")
    assert naming.resolve_naming(tmp_path, override="AGENTS.md").doc_name == "AGENTS.md"


def test_a_readme_map_is_recognised_not_reported_missing(documented_package):
    """The defect verbatim: with the AGENTS.md constant this folder was MISSING."""
    naming.use(naming.DocNaming("README.md"))
    assert classify(documented_package).state is not FolderState.MISSING

    naming.use(naming.DocNaming("AGENTS.md"))
    assert classify(documented_package).state is FolderState.MISSING


def test_a_map_without_its_lock_does_not_fail_the_check(documented_package):
    """No lock = no cache = nothing proves drift. A clean clone must not fail."""
    naming.use(naming.DocNaming("README.md"))
    status = classify(documented_package)

    assert status.state is FolderState.UNLOCKED
    assert status.needs_attention is False


def test_scan_of_a_documented_tree_flags_nothing(documented_package, tmp_path):
    naming.use(naming.DocNaming("README.md"))
    flagged = [s for s in scan(tmp_path) if s.needs_attention]

    assert flagged == []
