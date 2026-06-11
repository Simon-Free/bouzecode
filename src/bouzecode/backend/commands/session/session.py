# [desc] Session management utilities for saving, checkpointing, and restoring chat sessions as JSON. [/desc]
"""Session management: save, progressive save, session data, where."""
from __future__ import annotations

import json
import os
import signal
import threading
import uuid
from datetime import datetime
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode.ui.ansi import clr, info, ok, warn, err


def _build_session_data(state, session_id: str | None = None, model: str | None = None) -> dict:
    first_msg = ""
    for m in state.messages:
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, list):
                c = next((b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"), "")
            if c:
                first_msg = c.replace("\n", " ").strip()[:80]
            break
    from bouzecode.backend.tools.state import get_file_snapshots
    max_snapshot_size = 50_000
    raw_snapshots = get_file_snapshots()
    truncated_snapshots = {}
    for fpath, snap in raw_snapshots.items():
        truncated_snapshots[fpath] = {
            "before": snap["before"][:max_snapshot_size] if len(snap["before"]) > max_snapshot_size else snap["before"],
            "after": snap["after"][:max_snapshot_size] if len(snap["after"]) > max_snapshot_size else snap["after"],
            "is_new": snap.get("is_new", False),
        }

    from ...agent.thinking_parser import strip_thinking_tags, strip_tool_use_xml

    def _clean_message(m):
        content = m.get("content", "")
        if m.get("role") == "assistant" and isinstance(content, str) and content:
            cleaned = strip_tool_use_xml(content)
            if not cleaned:
                cleaned = "."
            return {**m, "content": cleaned}
        if isinstance(content, list):
            return {**m, "content": [
                b if isinstance(b, dict) else b.model_dump()
                for b in content
            ]}
        return m

    return {
        "session_id": session_id or uuid.uuid4().hex[:8],
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": model or "",
        "first_message": first_msg,
        "messages": [_clean_message(m) for m in state.messages],
        "turn_count": state.turn_count,
        "user_loop_count": getattr(state, "user_loop_count", 0),
        "total_tool_calls": getattr(state, "total_tool_calls", 0),
        "meta_only_nudges": getattr(state, "meta_only_nudges", 0),
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "total_cache_read_tokens": getattr(state, "total_cache_read_tokens", 0),
        "total_cache_creation_tokens": getattr(state, "total_cache_creation_tokens", 0),
        "compaction_log": getattr(state, "compaction_log", []),
        "distinct_base": getattr(state, "distinct_base", 0),
        "file_snapshots": truncated_snapshots,
        "gc_state": {
            "notes": state.context_state.notes,
        },
        "notes_timeline": getattr(state, "notes_timeline", []),
        "thinking_log": getattr(state, "thinking_log", []),
        "last_api_payload": getattr(state, "last_api_payload", []),
        "system_prompt": getattr(state, "system_prompt", ""),
        "bouzecode_commit": getattr(state, "bouzecode_commit", ""),
        "bouzecode_version": getattr(state, "bouzecode_version", ""),
        "close_reason": getattr(state, "close_reason", ""),
        "final_answer": getattr(state, "final_answer", ""),
    }


def _get_or_create_session_path(config: dict) -> Path:
    existing = config.get("_session_path")
    if existing:
        return Path(existing)

    from bouzecode.backend.core.config import DAILY_DIR
    now = datetime.now()
    sid = config.get("_session_id", uuid.uuid4().hex[:8])
    ts = now.strftime("%H%M%S")
    date_str = now.strftime("%Y-%m-%d")
    day_dir = DAILY_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"session_{ts}_{sid}.json"
    config["_session_path"] = str(path)
    return path


def _safe_write_json(path: Path, data, indent=None):
    """Atomic, interrupt-safe JSON write."""
    is_main = threading.current_thread() is threading.main_thread()
    old_handler = None
    if is_main:
        try:
            old_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (OSError, ValueError):
            pass
    try:
        text = json.dumps(data, ensure_ascii=False, default=str, indent=indent)
        tmp = path.with_suffix('.tmp')
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        for _attempt in range(10):
            try:
                os.replace(str(tmp), str(path))
                break
            except PermissionError:
                if _attempt == 9:
                    tmp.unlink(missing_ok=True)
                    raise
                import time; time.sleep(0.1)
    finally:
        if old_handler is not None:
            try:
                signal.signal(signal.SIGINT, old_handler)
            except (OSError, ValueError):
                pass


def _rotate_backup(path: Path) -> None:
    """Copy existing file to .bak before overwriting."""
    if path.exists():
        bak = path.with_suffix('.bak.json')
        try:
            import shutil
            shutil.copy2(str(path), str(bak))
        except Exception:
            pass


def _save_session_checkpoint(state, session_file: str, session_id: str | None = None, session_path: str | None = None) -> None:
    data = _build_session_data(state, session_id=session_id)
    if session_path:
        data["session_path"] = session_path
    _safe_write_json(Path(session_file), data)


def save_progressive(state, config: dict) -> None:
    if not state.messages:
        return
    path = _get_or_create_session_path(config)
    data = _build_session_data(state, session_id=config.get("_session_id"),
                               model=config.get("model"))
    _rotate_backup(path)
    _safe_write_json(path, data, indent=2)

    from bouzecode.backend.core.config import MR_SESSION_DIR
    MR_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    latest = MR_SESSION_DIR / "session_latest.json"
    _rotate_backup(latest)
    _safe_write_json(latest, data, indent=2)


def save_latest(args: str, state, config=None) -> bool:
    from bouzecode.backend.core.config import SESSION_HIST_FILE
    if not state.messages:
        return True

    cfg = config or {}
    save_progressive(state, cfg)
    session_path = _get_or_create_session_path(cfg)

    if SESSION_HIST_FILE.exists():
        try:
            hist = json.loads(SESSION_HIST_FILE.read_text(encoding="utf-8"))
        except Exception:
            hist = {"total_turns": 0, "sessions": []}
    else:
        hist = {"total_turns": 0, "sessions": []}

    data = _build_session_data(state, session_id=cfg.get("_session_id"),
                               model=cfg.get("model"))
    hist["sessions"].append(data)
    hist["total_turns"] = sum(s.get("turn_count", 0) for s in hist["sessions"])
    _rotate_backup(SESSION_HIST_FILE)
    _safe_write_json(SESSION_HIST_FILE, hist, indent=2)

    ok(f"Session saved \u2192 {session_path}")
    ok(f"             \u2192 {SESSION_HIST_FILE}  ({len(hist['sessions'])} sessions / {hist['total_turns']} total turns)")
    return True


def cmd_save(args: str, state, config) -> bool:
    from bouzecode.backend.core.config import SESSIONS_DIR
    sid = uuid.uuid4().hex[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = args.strip() or f"session_{ts}_{sid}.json"
    path = Path(fname) if "/" in fname else SESSIONS_DIR / fname
    data = _build_session_data(state, session_id=sid, model=config.get("model"))
    _safe_write_json(path, data, indent=2)
    ok(f"Session saved \u2192 {path}  (id: {sid})")
    return True


def cmd_where(_args: str, _state, config) -> bool:
    from datetime import datetime as _dt
    from bouzecode.backend.core.config import DAILY_DIR, MR_SESSION_DIR, SESSION_HIST_FILE

    today_dir = DAILY_DIR / _dt.now().strftime("%Y-%m-%d")
    latest = MR_SESSION_DIR / "session_latest.json"
    explicit = config.get("session_file")

    print()
    print(clr("Session log paths:", "bold"))
    latest_status = clr("(exists)", "green") if latest.exists() else clr("(not yet written)", "dim")
    print(f"  Latest (auto-saved on exit): {latest}  {latest_status}")
    print(f"  Today's daily folder:         {today_dir}")
    if today_dir.exists():
        recent = sorted(today_dir.glob("session_*.json"))[-5:]
        for f in recent:
            print(clr(f"    - {f.name}", "dim"))
    print(f"  Master history:               {SESSION_HIST_FILE}")
    if explicit:
        print(f"  Per-tool checkpoint:          {explicit}  " + clr("(--session-file)", "dim"))
    print(clr(f"  Runtime session id: {config.get('_session_id', 'unknown')}", "dim"))
    return True
