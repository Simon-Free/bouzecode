# [desc] Tracks file read/write state, caches content/mtimes, detects stale edits, and flags Telegram turns. [/desc]
# [desc] Tracks file read/write state, caches content/mtimes, detects stale edits, and flags Telegram turns. [/desc]
"""File state tracking and Telegram turn detection."""
import os
import threading
from pathlib import Path

_read_files: set[str] = set()
_file_mtime: dict[str, float] = {}
_file_content_cache: dict[str, str] = {}
_file_edit_snapshots: dict[str, dict] = {}


def _track_read(file_path: str, content: str | None = None) -> None:
    norm = os.path.normpath(file_path)
    _read_files.add(norm)
    try:
        _file_mtime[norm] = os.path.getmtime(file_path)
    except OSError:
        pass
    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace", newline="")
        except OSError:
            return
    _file_content_cache[norm] = content


def _stale_edit_warning(file_path: str) -> str | None:
    """If the file changed on disk since last Read, return a warning + diff."""
    from .ops.file_ops import generate_unified_diff, maybe_truncate_diff

    norm = os.path.normpath(file_path)
    if norm not in _file_mtime:
        return None
    try:
        current_mtime = os.path.getmtime(file_path)
    except OSError:
        return None
    if current_mtime == _file_mtime[norm]:
        return None
    cached = _file_content_cache.get(norm, "")
    try:
        current = Path(file_path).read_text(encoding="utf-8", errors="replace", newline="")
    except OSError:
        return None
    diff = generate_unified_diff(cached, current, Path(file_path).name)
    truncated = maybe_truncate_diff(diff) if diff else "(no textual diff available)"
    return (
        "[Warning] File was modified on disk since your last Read. "
        "Edit was applied to the current disk version. "
        f"Diff (your cached version \u2192 current disk):\n\n{truncated}\n"
    )


def _update_mtime_after_write(file_path: str, content: str | None = None) -> None:
    norm = os.path.normpath(file_path)
    _read_files.add(norm)
    try:
        _file_mtime[norm] = os.path.getmtime(file_path)
    except OSError:
        pass
    if content is not None:
        _file_content_cache[norm] = content


def record_file_snapshot(file_path: str, before: str, after: str, is_new: bool = False) -> None:
    """Record before/after content for a file edit. Keeps first 'before', updates 'after'."""
    norm = os.path.normpath(file_path)
    existing = _file_edit_snapshots.get(norm)
    if existing:
        existing["after"] = after
    else:
        _file_edit_snapshots[norm] = {"before": before, "after": after, "is_new": is_new}


def get_file_snapshots() -> dict[str, dict]:
    """Return a copy of all file edit snapshots {path: {before, after, is_new}}."""
    return dict(_file_edit_snapshots)


def _path_segments(p: str) -> list[str]:
    return [seg for seg in os.path.normpath(p).replace("\\", "/").split("/") if seg]


def _common_suffix_length(a: list[str], b: list[str]) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n].lower() == b[-1 - n].lower():
        n += 1
    return n


def find_closest_read_file(target: str) -> str | None:
    """Return the read-tracked file whose path best matches target.

    Match by basename; if several candidates share the basename, pick the one
    with the longest common path suffix. Return None if no candidate matches or
    if the top score is a tie between multiple candidates (ambiguous).
    """
    if not target or not _read_files:
        return None
    target_base = os.path.basename(os.path.normpath(target)).lower()
    if not target_base:
        return None
    candidates = [p for p in _read_files if os.path.basename(p).lower() == target_base]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    target_segs = _path_segments(target)
    scored = [(_common_suffix_length(target_segs, _path_segments(p)), p) for p in candidates]
    scored.sort(reverse=True)
    top = scored[0][0]
    if sum(1 for s, _ in scored if s == top) > 1:
        return None
    return scored[0][1]


def list_read_files_with_basename(basename: str) -> list[str]:
    """Return all tracked read files whose basename matches (case-insensitive)."""
    needle = basename.lower()
    return sorted(p for p in _read_files if os.path.basename(p).lower() == needle)


def clear_file_state() -> None:
    _read_files.clear()
    _file_mtime.clear()
    _file_content_cache.clear()
    _file_edit_snapshots.clear()


_tg_thread_local = threading.local()


def _is_in_tg_turn(config: dict) -> bool:
    return getattr(_tg_thread_local, "active", False) or bool(config.get("_in_telegram_turn", False))
