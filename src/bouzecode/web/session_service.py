# [desc] Loads agent session JSON and renders it to rich HTML, plan, and edited-files views. [/desc]
# [desc] Loads agent session JSON and renders it to rich HTML, plan, and edited-files views.
"""Load and render agent session JSON to HTML."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .html_renderer import parse_session_json, render_html

from . import files_diff_view
from .context_viewer import build_turn_breakdowns


_PLAN_HEADING_RE = re.compile(
    r"(?:^|\n)##\s*(?:Phase\s*2[:\s]|Plan\b)",
    re.IGNORECASE,
)
_PLAN_MARKER_RE = re.compile(
    r"(?:^|\n)I will (?:modify|create|change|update) \d+ files?:",
    re.IGNORECASE,
)


def extract_plan_content(session_path: str) -> str | None:
    """Return the plan content: last WritePlan tool call, or fallback to assistant text."""
    path = Path(session_path)
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    data = json.loads(raw)

    # 1. Prefer explicit WritePlan tool calls (join ALL plans with ---)
    all_plans = []
    for msg in data.get("messages", []):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if tc.get("name") == "WritePlan":
                content = tc.get("input", {}).get("content")
                if content and content.strip():
                    all_plans.append(content.strip())
    if all_plans:
        return "\n\n---\n\n".join(all_plans)

    # 2. Fallback: detect plan written as plain assistant text
    plan = None
    for msg in data.get("messages", []):
        if msg.get("role") != "assistant":
            continue
        text = msg.get("content", "")
        if not text:
            continue
        heading_match = _PLAN_HEADING_RE.search(text)
        marker_match = _PLAN_MARKER_RE.search(text)
        if heading_match or marker_match:
            start = min(
                m.start() for m in [heading_match, marker_match] if m is not None
            )
            plan = text[start:].strip()
    return plan


def render_session_file(session_path: str, finished: bool = True) -> str | None:
    """Load a session JSON file and return rendered HTML, or None if missing."""
    path = Path(session_path)
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    data = json.loads(raw)
    messages = data.get("messages", [])
    if not messages:
        return None
    meta = {k: data.get(k) for k in (
        "session_id", "saved_at", "turn_count", "first_message", "model",
        "total_input_tokens", "total_output_tokens",
        "total_cache_read_tokens", "total_cache_creation_tokens",
    )}
    blocks = parse_session_json(messages)
    breakdowns = build_turn_breakdowns(session_path)
    return render_html(blocks, finished=finished, meta=meta, turn_breakdowns=breakdowns)


def render_edited_files(session_path: str) -> str | None:
    """Build a self-contained HTML page showing all file diffs from the session."""
    path = Path(session_path)
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return files_diff_view.empty_page()
    data = json.loads(raw)
    snapshots: dict = data.get("file_snapshots", {})
    if not snapshots:
        return files_diff_view.empty_page()
    return files_diff_view.build_page(snapshots)
