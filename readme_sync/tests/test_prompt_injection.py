from __future__ import annotations

from bouzecode.backend.core.context import build_system_prompt_parts


def _write_root_map(root):
    (root / "AGENTS.md").write_text(
        "# repo/\n\nThe repo.\n\n"
        "## Subfolders\n\n"
        "| Folder | Purpose |\n|--------|---------|\n"
        "| [pkg/](pkg/AGENTS.md) | The pkg package. |\n",
        encoding="utf-8",
    )


def test_prompt_injects_reader_when_root_map_exists(tmp_path, monkeypatch):
    _write_root_map(tmp_path)
    monkeypatch.chdir(tmp_path)

    stable, volatile = build_system_prompt_parts()

    assert "Codebase navigation (AGENTS.md map)" in stable
    assert "## Subfolders" in stable
    assert "## Module Reference" in stable
    assert "Snippet(" in stable
    # The reader protocol lives in the STABLE (cached) half, never the volatile one.
    assert "Codebase navigation" not in volatile


def test_prompt_absent_without_root_map(tmp_path, monkeypatch):
    # No root AGENTS.md at all -> no navigation section.
    monkeypatch.chdir(tmp_path)

    stable, _volatile = build_system_prompt_parts()

    assert "Codebase navigation (AGENTS.md map)" not in stable
