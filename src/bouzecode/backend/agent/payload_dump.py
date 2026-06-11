# [desc] Per-turn API-payload dump to disk for offline debugging of context/compaction bugs. [/desc]
"""Write the exact messages sent to the LLM on each turn.

`state.last_api_payload` only holds the most recent turn's payload. When the
model misbehaves many turns into a session (e.g. complaining that its reads
were trashed), we need the full turn-by-turn trace. This module appends each
turn's payload to a JSONL file inside
`~/.bouzecode/debug_payloads/<session_id>/turns.jsonl`, one JSON object per
line: `{"turn": N, "timestamp": ..., "messages": [...], "gc_state": {...}}`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _payload_dir(session_id: str) -> Path:
    from ..core.config import CONFIG_DIR
    return CONFIG_DIR / "debug_payloads" / session_id


def dump_turn_payload(state, session_id: str, messages: list,
                      system_blocks: list | None = None,
                      token_counts: dict | None = None) -> None:
    if not session_id:
        return
    target_dir = _payload_dir(session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "turn": state.turn_count,
        "timestamp": time.time(),
        "messages": messages,
        "gc_state": {
            "notes": state.gc_state.notes,
        },
    }
    if system_blocks is not None:
        record["system_blocks"] = system_blocks
    if token_counts is not None:
        record["token_counts"] = token_counts
    with (target_dir / "turns.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
