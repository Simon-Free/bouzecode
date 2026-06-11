# [desc] Central registry for extra source directories injected via --extra-dir CLI flag. [/desc]
"""Central path registry for extra source directories.

Extra dirs follow the same structure as .bouzecode/:
  <dir>/skills/   → skills
  <dir>/mcp.json  → MCP servers
  <dir>/plugins/  → plugins
  <dir>/hooks/    → (future) hooks
"""
from __future__ import annotations

from pathlib import Path

_extra_dirs: list[Path] = []


def register_extra_dirs(dirs: list[Path | str]) -> None:
    """Register extra directories (called once at startup by main()). Deduplicates resolved paths."""
    global _extra_dirs
    seen: set[Path] = set()
    result: list[Path] = []
    for d in dirs:
        if d:
            p = Path(d).resolve()
            if p not in seen:
                seen.add(p)
                result.append(p)
    _extra_dirs = result


def add_extra_dir(path: Path | str) -> bool:
    """Append a single extra directory at runtime (no-op if already present). Returns True if added."""
    resolved = Path(path).resolve()
    if resolved not in _extra_dirs:
        _extra_dirs.append(resolved)
        return True
    return False


def get_extra_dirs() -> list[Path]:
    """Return registered extra directories (highest priority sources)."""
    return list(_extra_dirs)
