# [desc] Shared helpers for session pickers: state restore, label formatting, recent-session collection. [/desc]
"""Helpers shared by /load and /resume: restore state, build menu labels, list recent sessions."""
from __future__ import annotations

import json
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr
except ImportError:
    from bouzecode import clr


def restore_state(state, data: dict) -> None:
    from bouzecode.backend.context_manager import ContextState
    state.messages = data.get("messages", [])
    state.turn_count = data.get("turn_count", 0)
    state.user_loop_count = data.get("user_loop_count", 0)
    state.total_input_tokens = data.get("total_input_tokens", 0)
    state.total_output_tokens = data.get("total_output_tokens", 0)
    state.total_cache_read_tokens = data.get("total_cache_read_tokens", 0)
    state.total_cache_creation_tokens = data.get("total_cache_creation_tokens", 0)
    state.compaction_log = list(data.get("compaction_log") or [])
    state.distinct_base = data.get("distinct_base", 0)
    gc = data.get("context_state") or {}
    state.context_state = ContextState(notes=dict(gc.get("notes") or {}))
    state.notes_timeline = list(data.get("notes_timeline") or [])
    state.last_api_payload = data.get("last_api_payload", [])
    # Champs SAUVEGARDÉS mais jusqu'ici oubliés au reload → une session REPRISE paraissait
    # « jamais finie / 0 outil » (télémétrie fausse : 37 close=vide gonflés, digests trompeurs).
    # NB : on ne restaure PAS system_prompt/bouzecode_commit/version = valeurs du RUN COURANT.
    state.total_tool_calls = data.get("total_tool_calls", 0)
    state.meta_only_nudges = data.get("meta_only_nudges", 0)
    state.thinking_log = list(data.get("thinking_log") or [])
    state.close_reason = data.get("close_reason", "")
    state.final_answer = data.get("final_answer", "")


def _session_preview(meta: dict) -> str:
    preview = meta.get("first_message", "")
    if preview:
        return preview.replace("\n", " ").strip()[:80]
    for msg in meta.get("messages", []):
        if msg.get("role") == "user":
            c = msg.get("content", "")
            if isinstance(c, list):
                c = next((b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"), "")
            if c:
                return c.replace("\n", " ").strip()[:80]
    return ""


def format_session_label(path: Path, with_date: bool = False) -> str:
    """One-line menu label for a session file. ``with_date`` prefixes the day."""
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.name
    saved_at = meta.get("saved_at", "")
    when = saved_at if with_date else saved_at[-8:]
    sid = meta.get("session_id", "")
    turns = meta.get("turn_count", "?")
    preview = _session_preview(meta)
    label = f"{when}  id:{sid}  turns:{turns}"
    if preview:
        label += f'  "{preview}"'
    return label


def collect_recent_sessions() -> list[Path]:
    """All saved session files across daily/ dirs, newest first (by mtime)."""
    from bouzecode.backend.core.config import DAILY_DIR
    if not DAILY_DIR.exists():
        return []
    files: list[Path] = []
    for day in DAILY_DIR.iterdir():
        if not day.is_dir():
            continue
        for s in day.glob("session_*.json"):
            if s.name.endswith(".bak.json") or s.name.endswith(".tmp"):
                continue
            files.append(s)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files
