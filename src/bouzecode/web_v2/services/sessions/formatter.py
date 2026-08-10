# [desc] Shared formatting helpers: pretty-print JSON, truncate text blocks with zoom hints, extract overflow file paths. [/desc]
"""Shared formatting utilities for session display endpoints.

Used by overview (this ticket) and future zoom endpoints (T2).
"""
from __future__ import annotations

import json
import re


def pretty_json(obj_or_str) -> str:
    """Return indented JSON. Accepts dict/list or a JSON string.

    If input is a string that isn't valid JSON, returns it unchanged.
    """
    if isinstance(obj_or_str, str):
        try:
            obj = json.loads(obj_or_str)
        except (json.JSONDecodeError, ValueError):
            return obj_or_str
    else:
        obj = obj_or_str
    return json.dumps(obj, indent=2, ensure_ascii=False)


def truncate_block(
    text: str,
    head: int = 40,
    tail: int = 10,
    zoom_hint: str = "",
    is_error: bool = False,
) -> str:
    """Truncate text in the middle, keeping head and tail lines.

    Error results (is_error=True) are NEVER truncated — they're short by nature
    and must remain fully visible for debugging.

    Returns original text if it fits within head+tail lines.
    """
    if is_error:
        return text

    lines = text.split("\n")
    total = len(lines)

    if total <= head + tail:
        return text

    omitted = total - head - tail
    marker = f"[... {omitted} lignes omises — zoom: {zoom_hint}]"

    head_part = lines[:head]
    tail_part = lines[total - tail:]
    return "\n".join(head_part) + "\n" + marker + "\n" + "\n".join(tail_part)


_OVERFLOW_RE = re.compile(
    r"\[\.\.\.output truncated — \d+ lines total, full output saved to: ([^\]]+)\]"
)


def resolve_overflow_pointer(text: str) -> str | None:
    """Extract the overflow file path from a truncated tool output.

    The format is produced by backend/tools/ops/truncation.py:
      [...output truncated — N lines total, full output saved to: <path>]
      [Use Read(file_path="<path>") to see the complete output]

    Returns the path string if found, None otherwise.
    """
    m = _OVERFLOW_RE.search(text)
    if m:
        return m.group(1)
    return None
