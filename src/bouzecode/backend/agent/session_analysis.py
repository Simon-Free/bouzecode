# [desc] <thinking>
# The user wants a single-line description of what session_analysis.py does, under 100 characters.
# </thinking>
# 
# Segments a bouzecode session turn's API payload into cache-read, cache-write, and fresh text blocks. [/desc]
"""Extract raw text segments from a bouzecode session turn, categorized by cache status.

For each LLM turn, the payload sent to Anthropic is structured as:
  system_blocks = [stable_prefix+CC, tool_docs+CC, methodology+CC, delta+CC, volatile]
  messages = [msg1, msg2, ...]

The API returns token counts:
  - cache_read_tokens: tokens served from cache (prefix hit)
  - cache_creation_tokens: tokens written to cache at a breakpoint
  - input_tokens (fresh): tokens not cached (after last breakpoint)
  - output_tokens: the LLM response

This module segments the payload structurally based on cache_control markers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _extract_text(block: Any) -> str:
    """Extract plain text from a system block or message content."""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        if block.get("type") == "text":
            return block.get("text", "")
        return block.get("content", "") or block.get("text", "")
    if isinstance(block, list):
        return "\n".join(_extract_text(b) for b in block)
    return str(block)


def _has_cache_control(block: dict) -> bool:
    """Check if a system block has a cache_control marker."""
    return isinstance(block, dict) and "cache_control" in block


CONFIG_DIR = None  # Lazy-loaded


def _get_config_dir():
    global CONFIG_DIR
    if CONFIG_DIR is None:
        from ..core.config import CONFIG_DIR as _cd
        CONFIG_DIR = _cd
    return CONFIG_DIR


def load_payload_dump(session_id: str) -> list[dict]:
    """Load the JSONL payload dump for a session.

    Returns list of turn records sorted by turn number.
    """
    dump_file = CONFIG_DIR / "debug_payloads" / session_id / "turns.jsonl"
    if not dump_file.exists():
        return []
    records = []
    for line in dump_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    records.sort(key=lambda r: r.get("turn", 0))
    return records


def analyze_turn_segments(turn_record: dict) -> dict[str, list[str]]:
    """Segment a turn's payload into cache categories.

    Args:
        turn_record: A single record from the payload dump JSONL, containing:
            - system_blocks: list of system content blocks
            - messages: list of messages sent
            - token_counts: {in_tokens, out_tokens, cache_read_tokens, cache_creation_tokens}

    Returns:
        Dict with keys:
            - cached_blocks: list of text segments with cache_control (potentially cache_read or cache_write)
            - fresh_blocks: list of text segments without cache_control (always fresh/uncached)
            - messages: list of message text segments (always fresh/uncached)
            - out: the assistant response text (empty if not available in this record)
            - token_counts: the raw token counts for this turn

        Note: The exact split between cache_read and cache_write within cached_blocks
        depends on whether the cache prefix matched. Use token_counts to determine:
        - cache_read_tokens > 0 means some/all cached_blocks were served from cache
        - cache_creation_tokens > 0 means some cached_blocks were written to cache
        - in_tokens = fresh_blocks + messages (non-cached input)
    """
    system_blocks = turn_record.get("system_blocks", [])
    messages = turn_record.get("messages", [])
    token_counts = turn_record.get("token_counts", {})

    cached_blocks = []
    fresh_blocks = []

    for block in system_blocks:
        text = _extract_text(block)
        if not text:
            continue
        if _has_cache_control(block):
            cached_blocks.append(text)
        else:
            fresh_blocks.append(text)

    message_texts = []
    for msg in messages:
        content = msg.get("content", "")
        text = _extract_text(content)
        if text:
            message_texts.append(text)

    return {
        "cached_blocks": cached_blocks,
        "fresh_blocks": fresh_blocks,
        "messages": message_texts,
        "out": "",
        "token_counts": token_counts,
    }


def analyze_session_turn(session_id: str, turn_index: int) -> dict[str, list[str]]:
    """High-level: analyze a specific turn from a saved session's payload dump.

    Args:
        session_id: The session ID (used to find the JSONL dump)
        turn_index: 0-based index into the sorted turn records

    Returns:
        Same as analyze_turn_segments()

    Raises:
        IndexError: if turn_index is out of range
        FileNotFoundError: if no payload dump exists for this session
    """
    records = load_payload_dump(session_id)
    if not records:
        from ..core.config import CONFIG_DIR
        dump_file = CONFIG_DIR / "debug_payloads" / session_id / "turns.jsonl"
        raise FileNotFoundError(f"No payload dump found at {dump_file}")
    if turn_index < 0 or turn_index >= len(records):
        raise IndexError(
            f"Turn index {turn_index} out of range (0-{len(records)-1})"
        )
    return analyze_turn_segments(records[turn_index])
