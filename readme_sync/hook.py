from __future__ import annotations

import json
import sys
from pathlib import Path

from readme_sync.hashing import (
    CODE_EXTS,
    DOC_NAME,
    IGNORE_DIRS,
    set_lock_stale,
)


def _extract_file_path(payload: dict) -> str | None:
    """Pull the edited file path out of a PostToolUse payload."""
    tool_input = payload.get("tool_input") or {}
    return tool_input.get("file_path")


def _is_ignored(path: Path) -> bool:
    """True if any path component is in the ignore-list."""
    return any(part in IGNORE_DIRS for part in path.parts)


def should_mark_stale(file_path: str) -> Path | None:
    """Return the folder to flag stale, or None if the edit is a no-op.

    A no-op when: the file is the README itself, is not a code file, or lives
    under an ignored directory.
    """
    path = Path(file_path)
    if path.name == DOC_NAME:
        return None
    if path.suffix not in CODE_EXTS:
        return None
    if _is_ignored(path):
        return None
    return path.parent


def handle_payload(payload: dict) -> Path | None:
    """Process one PostToolUse payload. Marks the folder stale when relevant."""
    file_path = _extract_file_path(payload)
    if not file_path:
        return None
    folder = should_mark_stale(file_path)
    if folder is None:
        return None
    set_lock_stale(folder)
    return folder


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    payload = json.loads(raw)
    handle_payload(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
