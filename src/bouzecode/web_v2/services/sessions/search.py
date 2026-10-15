# [desc] Recherche transversale (grep regex) dans les messages de toutes les sessions connues. [/desc]
"""Expose grep_sessions() utilisé par la route GET /api/sessions/grep."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import store


@dataclass
class Match:
    key: str
    idx: int
    role: str
    name: str
    excerpt: str


def _excerpt(text: str, pattern: re.Pattern, max_chars: int = 120) -> str:
    """Return ±max_chars/2 around first match, newlines replaced by spaces."""
    m = pattern.search(text)
    if not m:
        return text[:max_chars]
    start = max(0, m.start() - max_chars // 2)
    end = min(len(text), m.end() + max_chars // 2)
    fragment = text[start:end].replace("\n", " ").replace("\r", "")
    if start > 0:
        fragment = "…" + fragment
    if end < len(text):
        fragment = fragment + "…"
    return fragment


def _message_text(message: dict) -> str:
    """Flatten message content (text + tool_calls json) for searching."""
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
    for tc in message.get("tool_calls") or []:
        parts.append(tc.get("name", ""))
        inp = tc.get("input")
        if isinstance(inp, str):
            parts.append(inp)
        elif isinstance(inp, dict):
            parts.append(json.dumps(inp, ensure_ascii=False))
    return "\n".join(parts)


def _matches_filters(message: dict, *, role: str | None) -> bool:
    if role and message.get("role") != role:
        return False
    return True


def _collect_refs(listing: dict, day: str | None) -> list[dict]:
    """Flatten list_sessions() output into [{key, ...}] applying day pre-filter."""
    refs = [a for a in listing.get("agents") or [] if not day or day in (a.get("saved_at") or "")]
    for day_group in listing.get("days") or []:
        if not day or day_group.get("date") == day:
            refs.extend(day_group.get("sessions") or [])
    return refs


def _session_messages(key: str, model: str | None) -> Sequence[dict] | None:
    """Messages d'une session, ou None si introuvable/illisible ou hors filtre `model`."""
    resolved = store.resolve(key)
    data = store.load_session_json(resolved.path) if resolved is not None else None
    if data is None:
        return None
    if model:
        session_model = data.get("model") or data.get("meta", {}).get("model", "")
        if model.lower() not in session_model.lower():
            return None
    return data.get("messages") or []


def _grep_messages(key: str, messages: Sequence[dict], pattern, role: str | None):
    for idx, msg in enumerate(messages):
        if not _matches_filters(msg, role=role):
            continue
        text = _message_text(msg)
        if pattern.search(text):
            yield {"key": key, "idx": idx, "role": msg.get("role", ""),
                   "name": msg.get("name", ""), "excerpt": _excerpt(text, pattern)}


def grep_sessions(
    q: str,
    *,
    day: str | None = None,
    model: str | None = None,
    role: str | None = None,
    limit: int = 50,
) -> dict:
    """Search across all known sessions. Returns {matches, scanned, truncated}."""
    pattern = re.compile(q, re.IGNORECASE)
    matches: list[dict] = []
    scanned = 0
    for ref in _collect_refs(store.list_sessions(), day):
        key = ref.get("key", "")
        messages = _session_messages(key, model)
        if messages is None:
            continue
        scanned += 1
        for match in _grep_messages(key, messages, pattern, role):
            matches.append(match)
            if len(matches) >= limit:
                return {"matches": matches, "scanned": scanned, "truncated": True}
    return {"matches": matches, "scanned": scanned, "truncated": False}
