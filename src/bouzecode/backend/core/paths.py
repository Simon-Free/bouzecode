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


def remove_extra_dir(path: Path | str) -> bool:
    """Drop a single extra directory from the in-memory registry. Returns True if removed."""
    global _extra_dirs
    resolved = Path(path).resolve()
    before = len(_extra_dirs)
    _extra_dirs = [d for d in _extra_dirs if d != resolved]
    return len(_extra_dirs) != before


def get_extra_dirs() -> list[Path]:
    """Return registered extra directories (highest priority sources)."""
    return list(_extra_dirs)


# --- Persistence: extra dirs survive across runs via config.json's `extra_dirs` list. ---

def load_persisted_extra_dirs() -> list[str]:
    """Read the persisted extra-dir paths from config.json (raw strings, unresolved)."""
    from .config import load_config
    raw = load_config().get("extra_dirs", [])
    return [str(p) for p in raw if p]


def register_persisted_extra_dirs() -> None:
    """Register the persisted extra dirs into the in-memory registry (call at startup)."""
    for p in load_persisted_extra_dirs():
        add_extra_dir(p)


def persist_extra_dir(path: Path | str) -> tuple[bool, str]:
    """Validate, register in-memory, and persist a new extra dir. Returns (ok, message)."""
    from .config import load_config, save_config
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        return False, f"dossier introuvable : {path}"
    resolved = resolved.resolve()
    cfg = load_config()
    dirs = [str(p) for p in cfg.get("extra_dirs", [])]
    if str(resolved) in dirs:
        return False, f"déjà enregistré : {resolved}"
    dirs.append(str(resolved))
    cfg["extra_dirs"] = dirs
    save_config(cfg)
    add_extra_dir(resolved)
    return True, str(resolved)


def unpersist_extra_dir(path: Path | str) -> bool:
    """Remove an extra dir from config.json and the in-memory registry. Returns True if removed."""
    from .config import load_config, save_config
    resolved = str(Path(path).expanduser().resolve())
    cfg = load_config()
    dirs = [str(p) for p in cfg.get("extra_dirs", [])]
    kept = [p for p in dirs if str(Path(p).resolve()) != resolved and p != resolved]
    if len(kept) == len(dirs):
        return False
    cfg["extra_dirs"] = kept
    save_config(cfg)
    remove_extra_dir(resolved)
    return True
