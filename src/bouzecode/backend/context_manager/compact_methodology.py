"""Structural compaction of the methodology note (no LLM calls).

Triggered when the note exceeds BOUZECODE_NOTE_COMPACT_TOKENS (chars//4).
Removes:
  - Duplicate snippet blocks (same path+ranges or path+symbol → keep last)
  - Snippet blocks whose source file no longer exists on disk
"""

from __future__ import annotations

import os
import re
from pathlib import Path

COMPACT_TOKENS_THRESHOLD = int(os.environ.get("BOUZECODE_NOTE_COMPACT_TOKENS", "20000"))

# Matches a snippet header line (both range-based and symbol-based)
_SNIPPET_HEADER_RE = re.compile(
    r"^## snippet: (?P<path>.+?)"
    r"(?: L(?P<start>\d+)-(?P<end>\d+)| :: (?P<symbol>[^\s—]+))"
    r"(?: — .*)?\s*$"
)


def _extract_snippet_key(header: str) -> str | None:
    """Return a dedup key from a snippet header, or None if not a snippet."""
    m = _SNIPPET_HEADER_RE.match(header.strip())
    if not m:
        return None
    path = m.group("path").strip()
    if m.group("symbol"):
        return f"{path}::{m.group('symbol')}"
    return f"{path}:L{m.group('start')}-{m.group('end')}"


def _file_exists(path_str: str) -> bool:
    """Check if a snippet source file exists (tolerant to formatting)."""
    try:
        return Path(path_str.strip()).exists()
    except (OSError, ValueError):
        return False


def _split_into_blocks(text: str) -> list[tuple[str, str | None]]:
    """Split methodology text into (block_text, snippet_key | None) pairs.

    A 'block' starts at each '## snippet:' header and extends until the next
    '## ' header (any kind) or end of text. Non-snippet content is grouped as
    blocks with key=None.
    """
    lines = text.split("\n")
    blocks: list[tuple[list[str], str | None]] = []
    current_lines: list[str] = []
    current_key: str | None = None

    for line in lines:
        if line.startswith("## snippet:"):
            # Flush previous block
            if current_lines:
                blocks.append((current_lines, current_key))
            current_lines = [line]
            current_key = _extract_snippet_key(line)
        elif line.startswith("## ") and current_key is not None:
            # New non-snippet heading after a snippet block
            if current_lines:
                blocks.append((current_lines, current_key))
            current_lines = [line]
            current_key = None
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append((current_lines, current_key))

    return [("\n".join(blines), key) for blines, key in blocks]


def compact_methodology(text: str) -> tuple[str, int]:
    """Compact the methodology note structurally.

    Returns (compacted_text, chars_removed).
    """
    if not text:
        return text, 0

    blocks = _split_into_blocks(text)

    # Pass 1: identify last occurrence of each snippet key (dedup → keep last)
    last_index: dict[str, int] = {}
    for i, (_, key) in enumerate(blocks):
        if key is not None:
            last_index[key] = i

    # Pass 2: filter blocks
    kept: list[str] = []
    removed_chars = 0

    for i, (block_text, key) in enumerate(blocks):
        if key is None:
            # Non-snippet content: always keep
            kept.append(block_text)
            continue

        # Duplicate check: only keep the last occurrence
        if last_index.get(key) != i:
            removed_chars += len(block_text)
            continue

        # Dead file check: extract path from key
        path_str = key.split("::")[0].split(":L")[0]
        if not _file_exists(path_str):
            removed_chars += len(block_text)
            continue

        kept.append(block_text)

    result = "\n".join(kept).strip()
    # Accurate removed calculation
    actual_removed = len(text) - len(result)
    return result, actual_removed


def maybe_compact(gc_state, note_key: str = "methodology") -> int:
    """Compact the methodology note if it exceeds the token threshold.

    Returns number of chars removed (0 if no compaction needed/done).
    """
    if COMPACT_TOKENS_THRESHOLD == 0:
        return 0

    text = gc_state.notes.get(note_key, "")
    estimated_tokens = len(text) // 4

    if estimated_tokens <= COMPACT_TOKENS_THRESHOLD:
        return 0

    compacted, chars_removed = compact_methodology(text)
    if chars_removed > 0:
        gc_state.notes[note_key] = compacted
        # Invalidate cache snapshot so next render rebuilds from scratch
        if hasattr(gc_state, "_methodology_cache_snapshot"):
            gc_state._methodology_cache_snapshot = None
    return chars_removed
