"""Per-turn context diagnostic: what the model saw at a given turn.

For each element sent to the model this turn we expose:
  - status_label: "cache read" | "cache write" | "fresh"
  - added_at_turn: the turn at which this element FIRST entered the context.

Reuses the existing context_viewer builder (single source of truth) so the
cache-status semantics stay consistent with the historical viewer.

GOLDEN RULE: we never surface a full payload; each item's `text` is truncated
to TEXT_CAP chars.
"""
from __future__ import annotations

import json
from pathlib import Path

from bouzecode.web_v2.runtime.context_viewer.builder import extract_per_call_data

TEXT_CAP = 20000

# Internal cache_status (from annotate_cache_status) -> user-facing label.
_STATUS_LABEL = {
    "cached": "cache read",
    "new-cache": "cache write",
    "fresh": "fresh",
}

# Which labels count as "delta" (added/written this turn) vs already-cached.
_DELTA_LABELS = {"fresh", "cache write"}


def _expose_item(item: dict) -> dict:
    status_label = _STATUS_LABEL.get(item.get("cache_status", "fresh"), "fresh")
    text = item.get("text") or ""
    if len(text) > TEXT_CAP:
        text = text[:TEXT_CAP] + "\n\u2026 [tronqué]"
    return {
        "kind": item.get("kind", ""),
        "label": item.get("label", ""),
        "preview": item.get("preview", ""),
        "text": text,
        "est_tokens": item.get("est_tokens", 0),
        "status_label": status_label,
        "added_at_turn": item.get("added_at_turn"),
        "payload_idx": item.get("payload_idx"),
    }


def _notes_delta_for_turn(session_path: str, turn_n: int) -> dict | None:
    try:
        data = json.loads(Path(session_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for entry in data.get("notes_timeline", []) or []:
        if entry.get("turn") == turn_n:
            delta = entry.get("delta") or {}
            return {
                "added": delta.get("added", []),
                "updated": delta.get("updated", []),
                "removed": delta.get("removed", []),
            }
    return None


def build_turn_context_diag(session_path: str, turn_n: int) -> dict | None:
    """Return the diagnostic for turn `turn_n`, or None if unavailable.

    None is returned when the session cannot be parsed or the debug payload
    dumps for the session are missing (nothing to diagnose).
    """
    data = extract_per_call_data(session_path)
    if data is None or data.get("missing_dumps"):
        return None

    call = next((c for c in data.get("calls", []) if c.get("turn") == turn_n), None)
    if call is None or not call.get("items"):
        return None

    # Recompute each item's origin turn ("added_at_turn"): the earliest turn at
    # which an item with the SAME CONTENT first entered the context. The builder
    # does not persist this, but it is fully recomputable from the per-call
    # breakdown. Identity = the item's raw content (text, else preview) + kind —
    # NOT payload_idx, which is a per-turn POSITION index (reused every turn and
    # None for system/notes), so it cannot identify a logical entry across turns.
    def _content_key(it: dict) -> str:
        return f"{it.get('kind', '')}\x00{it.get('text') or it.get('preview') or ''}"

    origin_by_key: dict[str, int] = {}
    first_item_by_key: dict[str, dict] = {}
    for prev in sorted(data.get("calls", []), key=lambda c: c.get("turn", 0)):
        prev_turn = prev.get("turn")
        if prev_turn is None:
            continue
        for it in prev.get("items", []):
            k = _content_key(it)
            if k not in origin_by_key:
                origin_by_key[k] = prev_turn
                first_item_by_key[k] = it
    for it in call["items"]:
        st = _STATUS_LABEL.get(it.get("cache_status", "fresh"), "fresh")
        if st in _DELTA_LABELS:
            # Fresh / cache-write = billed and (re)sent THIS turn → origin = turn_n.
            it["added_at_turn"] = turn_n
        else:
            # Cache read = already in the prefix → origin = earliest turn seen.
            it["added_at_turn"] = origin_by_key.get(_content_key(it))

    # DELTA = what is billed / (re)sent THIS turn = the current call's items whose
    # Anthropic cache status is fresh or cache-write (NOT read from the prefix).
    exposed_current = [_expose_item(it) for it in call["items"]]
    delta_items = [i for i in exposed_current if i.get("status_label") in _DELTA_LABELS]
    delta_keys = {
        f"{i.get('kind', '')}\x00{i.get('text') or i.get('preview') or ''}"
        for i in delta_items
    }

    # CACHED = the items ACTUALLY read from the prefix cache THIS turn, i.e. the
    # current call's wire items whose Anthropic cache status is "cache read".
    # `call["items"]` is the REAL wire payload of the turn (build_items_for_payload
    # over the dumped messages, annotated by annotate_cache_status) — it already
    # reflects exactly what was sent/cache-read. We MUST NOT reconstruct history
    # from earlier turns (origin < turn_n): doing so resurrected items that were
    # evicted/compacted out of the wire and force-marked them "cached", which
    # over-reported every past tool_call as cached in the diag. Each cache-read
    # item keeps its recomputed origin turn (added_at_turn set above) for grouping.
    cached_items = [i for i in exposed_current if i.get("status_label") == "cache read"]
    cached_items.sort(key=lambda i: (i.get("added_at_turn") is None, i.get("added_at_turn") or 0))

    return {
        "session_id": data.get("session_id", "?"),
        "model": data.get("model", "?"),
        "turn": turn_n,
        "timestamp": call.get("timestamp"),
        "totals": {
            "api_input_tokens": call.get("api_input_tokens", 0),
            "api_output_tokens": call.get("api_output_tokens", 0),
            "api_cache_read": call.get("api_cache_read", 0),
            "api_cache_create": call.get("api_cache_create", 0),
            "est_message_tokens": call.get("est_message_tokens", 0),
            "wire_message_count": call.get("wire_message_count", 0),
        },
        "delta_items": delta_items,
        "cached_items": cached_items,
        "notes_delta": _notes_delta_for_turn(session_path, turn_n),
    }
