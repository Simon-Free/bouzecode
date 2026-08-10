# [desc] Test helper that writes an AGENTS.md plus a coherent fresh .agents.lock for a folder's code. [/desc]
from __future__ import annotations

from pathlib import Path

from readme_sync.hashing import write_lock


def make_fresh(folder: Path, purpose: str = "Test folder.") -> None:
    """Write an AGENTS.md + a coherent (fresh) .agents.lock for a folder's current code."""
    name = folder.name
    (folder / "AGENTS.md").write_text(
        f"# {name}/\n\n{purpose}\n\n## Module Reference\n\n"
        "| File | Lines | Purpose |\n|------|-------|---------|\n",
        encoding="utf-8",
    )
    write_lock(folder, stale=False)
