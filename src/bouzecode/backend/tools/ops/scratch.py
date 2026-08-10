# [desc] Session-scoped scratch storage mapping logical temp=True paths to real files outside the git worktree. [/desc]
"""Scratch storage for temporary agent files (temp=True on Write/Edit).

Rationale: agents sometimes need throwaway working files (extraction dumps,
captured fixtures, timelines, or a script to run once). Without a dedicated
channel these end up written into the cwd and accidentally committed. temp=True
routes them to a scratch directory OUTSIDE the git worktree (under the OS temp
dir), so git can never see them.

The agent addresses files by a LOGICAL path (whatever it passed as file_path).
We map that logical path to a REAL path inside the scratch dir. Read/Edit resolve
a logical path back to its real file transparently; Bash substitutes logical
paths by their real path in the command; Glob/Grep also surface scratch files.

Scope & lifetime: the scratch dir is keyed by SESSION id (not process pid), and
the logical->real registry is persisted as JSON inside that dir. This makes it
resume-safe: a new worker process for the same session reloads the registry and
keeps resolving the same temp files. Destruction happens at real session end
(clear_file_state -> cleanup_scratch), NOT at process exit — so a pause/resume
does not wipe an agent's temp files.
"""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

# logical path (as passed by the model) -> real path on disk (inside scratch dir)
_registry: dict[str, str] = {}
_scratch_dir: Path | None = None
_session_id: str | None = None
_loaded: bool = False

_REGISTRY_FILE = "_registry.json"


def set_scratch_session(session_id: str | None) -> None:
    """Bind scratch storage to a session id (called at session boot, like checkpoint).

    Changing session resets the in-memory cache so the next access rebinds the
    scratch dir and reloads the persisted registry for that session.
    """
    global _session_id, _scratch_dir, _loaded
    if session_id != _session_id:
        _session_id = session_id
        _scratch_dir = None
        _registry.clear()
        _loaded = False


def _get_scratch_dir() -> Path:
    """Return (creating if needed) the per-session scratch directory."""
    global _scratch_dir
    if _scratch_dir is None:
        sid = _session_id or "default"
        base = Path(tempfile.gettempdir()) / "bouzecode_scratch" / _sanitize_session(sid)
        base.mkdir(parents=True, exist_ok=True)
        _scratch_dir = base
    return _scratch_dir


def _sanitize_session(session_id: str) -> str:
    """Make a session id safe as a single directory name."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return safe or "default"


def _registry_path() -> Path:
    return _get_scratch_dir() / _REGISTRY_FILE


def _ensure_loaded() -> None:
    """Lazily reload the persisted registry once per process/session binding."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    rp = _registry_path()
    if rp.exists():
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for logical, real in data.items():
                    _registry.setdefault(str(logical), str(real))
        except (OSError, ValueError):
            pass


def _persist() -> None:
    try:
        _registry_path().write_text(
            json.dumps(_registry, ensure_ascii=False, indent=0),
            encoding="utf-8",
        )
    except OSError:
        pass


def _sanitize(logical: str) -> str:
    """Derive a unique, readable real filename from a logical path.

    Keeps the basename for readability, appends a short hash of the full logical
    path to guarantee uniqueness (two different logical paths sharing a basename
    must not collide).
    """
    name = Path(logical).name or "scratch"
    digest = hashlib.sha1(logical.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{digest}__{name}"


def resolve_scratch_path(logical: str) -> Path:
    """Map a logical path to its real scratch path (idempotent), registering it."""
    _ensure_loaded()
    existing = _registry.get(logical)
    if existing is not None:
        return Path(existing)
    real = _get_scratch_dir() / _sanitize(logical)
    _registry[logical] = str(real)
    _persist()
    return real


def register_temp(logical: str, real: str | Path) -> None:
    _ensure_loaded()
    _registry[logical] = str(real)
    _persist()


def lookup_temp(logical: str) -> str | None:
    """Return the real scratch path for a logical path, or None if not a temp file."""
    _ensure_loaded()
    return _registry.get(logical)


def all_temp_paths() -> list[tuple[str, str]]:
    """Return (logical, real) pairs for every registered temp file this session."""
    _ensure_loaded()
    return [(logical, real) for logical, real in _registry.items()]


def is_scratch_path(path: str | Path) -> bool:
    """True if the given real path lives inside the scratch directory."""
    if _scratch_dir is None:
        return False
    try:
        Path(path).resolve().relative_to(_scratch_dir.resolve())
        return True
    except (ValueError, OSError):
        return False


def cleanup_scratch() -> None:
    """Destroy the current session's scratch directory and clear the registry.

    Called at real session end (clear_file_state). NOT registered with atexit,
    so a pause/resume (new process, same session) keeps the temp files alive.
    """
    global _scratch_dir, _loaded
    _registry.clear()
    _loaded = False
    if _scratch_dir is not None:
        shutil.rmtree(_scratch_dir, ignore_errors=True)
        _scratch_dir = None
