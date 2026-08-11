# [desc] Detects (and reverts) any write a test makes to this checkout's tracked files. [/desc]
"""A test must never modify the git-tracked working tree.

Two files in this repository are literally test residue that got committed:
`main.py` holds `print("hello")` (written by an e2e Write call) and
`.nano_claude/plans/default.md` holds `# Plan` (written by plan mode). Both come
from tests that let the agent run with `Path.cwd()` on the real checkout.

Watched: every tracked file sitting directly at the repo root, plus everything
under `.nano_claude/` — the two places tools write relative to the cwd. Change
detection is `(mtime_ns, size)`, so re-writing identical bytes still counts: the
point is that no test writes there at all.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def tracked_root_files(root: Path) -> list[Path]:
    """Tracked files sitting directly at the repo root (no subdirectory)."""
    result = subprocess.run(
        ["git", "ls-files"], cwd=str(root), capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return [root / name for name in result.stdout.splitlines() if "/" not in name]


def watched_paths(root: Path) -> list[Path]:
    artifacts = [p for p in (root / ".nano_claude").rglob("*") if p.is_file()]
    return sorted(set(tracked_root_files(root)) | set(artifacts))


def snapshot(paths: list[Path]) -> dict[Path, tuple[int, int] | None]:
    """{path: (mtime_ns, size)} — None when the file does not exist."""
    marks: dict[Path, tuple[int, int] | None] = {}
    for path in paths:
        if path.exists():
            stat = path.stat()
            marks[path] = (stat.st_mtime_ns, stat.st_size)
        else:
            marks[path] = None
    return marks


def revert(root: Path, paths: list[Path]) -> None:
    """Put the checkout back, so one offender cannot cascade into the whole run."""
    relative = [str(p.relative_to(root)) for p in paths]
    subprocess.run(["git", "checkout", "--", *relative],
                   cwd=str(root), capture_output=True, text=True)
