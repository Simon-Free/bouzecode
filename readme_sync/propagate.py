from __future__ import annotations

import re
from pathlib import Path

from .contract import purpose_of
from .hashing import (
    DOC_NAME,
    code_files,
    git_ignored_paths,
    is_ignored_dir,
    iter_code_folders,
)

SUBFOLDERS_HEADING = "## Subfolders"


def create_root_map(root: Path) -> Path:
    """Write root/AGENTS.md as a flat map of every code folder + its 1-line purpose.

    This is a pure map (no ## Module Reference): H1 + one-line purpose + a
    ## Subfolders table listing every non-ignored code folder under root (except
    root itself), each with the purpose extracted from its own AGENTS.md. Idempotent.
    """
    root = root.resolve()
    rows = []
    for folder in sorted(iter_code_folders(root), key=lambda p: str(p).lower()):
        if folder == root:
            continue
        if not has_code_anywhere(folder):
            continue
        rel = folder.relative_to(root).as_posix()
        purpose = _child_purpose(folder)
        rows.append(f"| [{rel}/]({rel}/{DOC_NAME}) | {purpose} |")
    body = "\n".join(rows)
    table = (
        f"{SUBFOLDERS_HEADING}\n\n"
        "| Folder | Purpose |\n"
        "|--------|---------|\n"
        f"{body}\n"
    )
    out = root / DOC_NAME
    if out.exists():
        # Non-destructive: preserve the existing root AGENTS.md, just upsert
        # the ## Subfolders map. Never overwrite the H1 / prose.
        current = out.read_text(encoding="utf-8")
        out.write_text(upsert_subfolders_section(current, table), encoding="utf-8")
        return out
    md = (
        f"# {root.name}/\n\n"
        "Map of every documented code folder in this repository.\n\n"
        f"{table}"
    )
    out.write_text(md, encoding="utf-8")
    return out


def has_code_anywhere(folder: Path) -> bool:
    """True if the folder or any non-ignored descendant contains a code file."""
    for sub in iter_code_folders(folder):
        if code_files(sub):
            return True
    return False


def code_subfolders(parent: Path) -> list[Path]:
    """Direct child folders (non-ignored) that contain code somewhere below them.

    Git-ignored folders are skipped, exactly like `create_root_map`. Without this the
    two layers disagreed: the root map (built on `iter_code_folders`, which asks git)
    dropped a scratch folder, while parent propagation (this function) re-added it on
    the next refresh — with a dead link, since a git-ignored folder has no AGENTS.md.
    """
    ignored = git_ignored_paths(parent)
    out = [
        child for child in sorted(parent.iterdir(), key=lambda p: p.name)
        if child.is_dir()
        and not is_ignored_dir(child.name)
        and child.resolve() not in ignored
        and has_code_anywhere(child)
    ]
    return out


def _child_purpose(child: Path) -> str:
    doc = child / DOC_NAME
    if not doc.exists():
        return "—"
    purpose = purpose_of(doc.read_text(encoding="utf-8"))
    return purpose or "—"


def subfolders_table(parent: Path) -> str:
    """Render the ## Subfolders section for a parent from its real child folders."""
    rows = []
    for child in code_subfolders(parent):
        name = child.name
        purpose = _child_purpose(child)
        rows.append(f"| [{name}/]({name}/{DOC_NAME}) | {purpose} |")
    body = "\n".join(rows)
    return (
        f"{SUBFOLDERS_HEADING}\n\n"
        "| Folder | Purpose |\n"
        "|--------|---------|\n"
        f"{body}\n"
    )


def upsert_section(md: str, heading: str, block: str) -> str:
    """Replace an existing `heading` block (## ...), or insert it before the first
    other ## section (falling back to just after the purpose line / at the end).
    Preserves all other content (human prose) untouched."""
    lines = md.splitlines()

    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break

    if start is not None:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break
        new_block = block.rstrip("\n").splitlines()
        rebuilt = lines[:start] + new_block + [""] + lines[end:]
        return "\n".join(rebuilt).rstrip("\n") + "\n"

    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            insert_at = i
            break
    new_block = block.rstrip("\n").splitlines() + [""]
    if insert_at is None:
        rebuilt = lines + [""] + new_block
    else:
        rebuilt = lines[:insert_at] + new_block + lines[insert_at:]
    return "\n".join(rebuilt).rstrip("\n") + "\n"


def upsert_subfolders_section(md: str, table: str) -> str:
    """Replace an existing ## Subfolders block, or insert one before the first
    other ## section (falling back to just after the purpose line / at the end)."""
    lines = md.splitlines()

    start = None
    for i, line in enumerate(lines):
        if line.strip() == SUBFOLDERS_HEADING:
            start = i
            break

    if start is not None:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break
        new_block = table.rstrip("\n").splitlines()
        rebuilt = lines[:start] + new_block + [""] + lines[end:]
        return "\n".join(rebuilt).rstrip("\n") + "\n"

    # No existing section: insert before the first other ## heading.
    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            insert_at = i
            break
    block = table.rstrip("\n").splitlines() + [""]
    if insert_at is None:
        rebuilt = lines + [""] + block
    else:
        rebuilt = lines[:insert_at] + block + lines[insert_at:]
    return "\n".join(rebuilt).rstrip("\n") + "\n"


def refresh_parent(parent: Path) -> None:
    """Rewrite the parent's AGENTS.md ## Subfolders table from its real children.

    No-op if the parent has no AGENTS.md or no code subfolders. Does NOT touch the
    parent's .agents.lock (its code manifest is unchanged; AGENTS.md is excluded)."""
    if not code_subfolders(parent):
        return
    doc = parent / DOC_NAME
    if not doc.exists():
        return
    md = doc.read_text(encoding="utf-8")
    updated = upsert_subfolders_section(md, subfolders_table(parent))
    if updated != md:
        doc.write_text(updated, encoding="utf-8")


def propagate_up(folder: Path, root: Path) -> None:
    """Walk from folder's parent up to (and including) root, refreshing each
    parent's Subfolders table so the child's purpose line is mirrored upward."""
    folder = folder.resolve()
    root = root.resolve()
    parent = folder.parent
    while parent.is_relative_to(root):
        refresh_parent(parent)
        if parent == root:
            break
        parent = parent.parent
