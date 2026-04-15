# [desc] Session management utilities for saving, checkpointing, and restoring chat sessions as JSON. [/desc]
"""Session management: save, progressive save, session data, where."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

try:
    from ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode import clr, info, ok, warn, err


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
    from tools.state import get_file_snapshots
    max_snapshot_size = 50_000
    raw_snapshots = get_file_snapshots()
    truncated_snapshots = {}
    for fpath, snap in raw_snapshots.items():
        truncated_snapshots[fpath] = {
            "before": snap["before"][:max_snapshot_size] if len(snap["before"]) > max_snapshot_size else snap["before"],
            "after": snap["after"][:max_snapshot_size] if len(snap["after"]) > max_snapshot_size else snap["after"],
            "is_new": snap.get("is_new", False),
        }

    return {
        "session_id": session_id or uuid.uuid4().hex[:8],
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": model or "",
        "first_message": first_msg,
        "messages": [
            m if not isinstance(m.get("content"), list) else
            {**m, "content": [
                b if isinstance(b, dict) else b.model_dump()
                for b in m["content"]
            ]}
            for m in state.messages
        ],
        "turn_count": state.turn_count,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "total_cache_read_tokens": getattr(state, "total_cache_read_tokens", 0),
        "total_cache_creation_tokens": getattr(state, "total_cache_creation_tokens", 0),
        "compaction_log": getattr(state, "compaction_log", []),
        "distinct_base": getattr(state, "distinct_base", 0),
        "file_snapshots": truncated_snapshots,
    }


def _get_or_create_session_path(config: dict) -> Path:
    existing = config.get("_session_path")
    if existing:
        return Path(existing)

    from config import DAILY_DIR
    now = datetime.now()
    sid = config.get("_session_id", uuid.uuid4().hex[:8])
    ts = now.strftime("%H%M%S")
    date_str = now.strftime("%Y-%m-%d")
    day_dir = DAILY_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"session_{ts}_{sid}.json"
    config["_session_path"] = str(path)
    return path


def _save_session_checkpoint(state, session_file: str) -> None:
    data = _build_session_data(state)
    Path(session_file).write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")


def save_progressive(state, config: dict) -> None:
    if not state.messages:
        return
    path = _get_or_create_session_path(config)
    data = _build_session_data(state, session_id=config.get("_session_id"),
                               model=config.get("model"))
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    from config import MR_SESSION_DIR
    MR_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    latest = MR_SESSION_DIR / "session_latest.json"
    latest.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def save_latest(args: str, state, config=None) -> bool:
    from config import SESSION_HIST_FILE
    if not state.messages:
        return True

    cfg = config or {}
    save_progressive(state, cfg)
    session_path = _get_or_create_session_path(cfg)

    if SESSION_HIST_FILE.exists():
        try:
            hist = json.loads(SESSION_HIST_FILE.read_text())
        except Exception:
            hist = {"total_turns": 0, "sessions": []}
    else:
        hist = {"total_turns": 0, "sessions": []}

    data = _build_session_data(state, session_id=cfg.get("_session_id"),
                               model=cfg.get("model"))
    hist["sessions"].append(data)
    hist["total_turns"] = sum(s.get("turn_count", 0) for s in hist["sessions"])
    SESSION_HIST_FILE.write_text(json.dumps(hist, indent=2, default=str))

    ok(f"Session saved \u2192 {session_path}")
    ok(f"             \u2192 {SESSION_HIST_FILE}  ({len(hist['sessions'])} sessions / {hist['total_turns']} total turns)")
    return True


def cmd_save(args: str, state, config) -> bool:
    from config import SESSIONS_DIR
    sid = uuid.uuid4().hex[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = args.strip() or f"session_{ts}_{sid}.json"
    path = Path(fname) if "/" in fname else SESSIONS_DIR / fname
    data = _build_session_data(state, session_id=sid, model=config.get("model"))
    path.write_text(json.dumps(data, indent=2, default=str))
    ok(f"Session saved \u2192 {path}  (id: {sid})")
    return True


def cmd_where(_args: str, _state, config) -> bool:
    from datetime import datetime as _dt
    from config import DAILY_DIR, MR_SESSION_DIR, SESSION_HIST_FILE

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
