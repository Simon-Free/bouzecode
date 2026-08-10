# [desc] Per-LLM-call breakdowns built from the on-disk turn dumps (turns.jsonl) — single source of truth, no manual replay. [/desc]
"""Builds per-LLM-call context breakdowns from the agent's payload dumps.

Reads ``~/.bouzecode/debug_payloads/<session_id>/turns.jsonl`` which contains
the *exact* messages sent to the API on each turn (with ``_cache_breakpoint``
markers and the GC state at that moment). Joining by turn number with the
session JSON's ``compaction_log`` adds the API token counts.
"""
import json
import types
from pathlib import Path

from .items import (
    annotate_cache_status, build_items_for_payload, build_tool_call_index,
    estimate_tokens, message_text,
)


def _load_turn_dumps(session_id: str) -> dict[int, dict]:
    """Return {turn_number: dump_record} or {} if no dump file exists.

    Le payload complet de chaque tour est une VUE : le journal ne stocke que ce qui change
    d'un appel au suivant, et `payload_dump.load_turn_map` le reconstitue (cf. l'en-tête de
    `backend/agent/payload_dump.py`). Ce module n'a donc jamais à connaître la forme du
    stockage — et `_payload_divergence` ci-dessous reste le juge du cache, inchangé."""
    if not session_id:
        return {}
    from bouzecode.backend.core.payload_view import load_turn_map
    return load_turn_map(session_id)


def _context_state_from_dump(dump: dict):
    """Adapt the dumped context_state dict into the ContextState shape we use (notes-only).

    Old dumps store the state under 'gc_state' instead of 'context_state'.
    """
    raw = dump.get("context_state") or dump.get("gc_state") or {}
    return types.SimpleNamespace(notes=raw.get("notes") or {})


def _api_tokens_for(entry: dict | None, dump: dict | None) -> dict[str, int]:
    """Return api_* token counts: compaction_log entry is authoritative; else fall
    back to the dump's token_counts (post-call record)."""
    if entry is not None:
        return {
            "api_input_tokens": entry.get("api_input_tokens", 0),
            "api_output_tokens": entry.get("api_output_tokens", 0),
            "api_cache_read": entry.get("api_cache_read", 0),
            "api_cache_create": entry.get("api_cache_create", 0),
        }
    tc = (dump or {}).get("token_counts") or {}
    return {
        "api_input_tokens": tc.get("in_tokens", 0),
        "api_output_tokens": tc.get("out_tokens", 0),
        "api_cache_read": tc.get("cache_read_tokens", 0),
        "api_cache_create": tc.get("cache_creation_tokens", 0),
    }


def _find_breakpoint(payload: list[dict]) -> int:
    for i, msg in enumerate(payload):
        if msg.get("_cache_breakpoint"):
            return i
    return -1


def _msg_signature(msg: dict) -> tuple:
    role = msg.get("role", "")
    content = msg.get("content", "")
    if isinstance(content, list):
        content = json.dumps(content, ensure_ascii=False, sort_keys=True)
    tcs = msg.get("tool_calls") or []
    tc_sig = json.dumps(
        [{"id": tc.get("id"), "name": tc.get("name"), "input": tc.get("input")} for tc in tcs],
        ensure_ascii=False, sort_keys=True,
    )
    return (role, content or "", msg.get("tool_call_id", ""), tc_sig)


def _payload_divergence(prev: list[dict], cur: list[dict]) -> int:
    for i in range(min(len(prev), len(cur))):
        if _msg_signature(prev[i]) != _msg_signature(cur[i]):
            return i
    return min(len(prev), len(cur))


def _summarize_items(items: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    tokens_by_status: dict[str, int] = {}
    count_by_status: dict[str, int] = {}
    for item in items:
        status = item["cache_status"]
        tokens_by_status[status] = tokens_by_status.get(status, 0) + item["est_tokens"]
        count_by_status[status] = count_by_status.get(status, 0) + 1
    return tokens_by_status, count_by_status


def _resolve_model(session_path: str, data_model: str) -> str:
    """Resolve the session model, falling back to the web-agent sidecar.

    For web agents the session file is `<agent_id>.session.json` next to a
    `<agent_id>.json` metadata file carrying the real model. CLI sessions have
    no sidecar, so the empty model is returned unchanged.
    """
    if data_model:
        return data_model
    name = Path(session_path).name
    suffix = ".session.json"
    if not name.endswith(suffix):
        return data_model
    agent_id = name[: -len(suffix)]
    sidecar = Path(session_path).parent / f"{agent_id}.json"
    if not sidecar.exists():
        return data_model
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    return meta.get("model") or data_model


def extract_per_call_data(session_path: str) -> dict | None:
    path = Path(session_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    raw_messages = data.get("messages", [])
    log = [e for e in data.get("compaction_log", []) if e.get("event") == "llm_call"]
    if not raw_messages:
        return None

    dumps = _load_turn_dumps(data.get("session_id", ""))
    if not dumps:
        return {
            "session_id": data.get("session_id", "?"),
            "model": _resolve_model(session_path, data.get("model") or "") or "?",
            "saved_at": data.get("saved_at", "?"),
            "first_message": data.get("first_message", ""),
            "system_prompt_tokens": estimate_tokens(data.get("system_prompt", "")),
            "calls": [],
            "missing_dumps": True,
        }

    system_prompt = data.get("system_prompt", "") or ""
    tc_index = build_tool_call_index(raw_messages)

    log_by_turn = {e.get("turn"): e for e in log}
    turn_numbers = sorted(set(log_by_turn) | set(dumps), key=lambda t: (t is None, t))

    calls: list[dict] = []
    prev_payload: list[dict] = []
    prev_bp = -1
    for turn in turn_numbers:
        entry = log_by_turn.get(turn)
        dump = dumps.get(turn)
        api = _api_tokens_for(entry, dump)
        timestamp = entry.get("timestamp") if entry else (dump or {}).get("timestamp")
        est_message_tokens = entry.get("est_message_tokens", 0) if entry else 0
        if not dump:
            calls.append({
                "turn": turn,
                "timestamp": timestamp,
                "user_prompt": "",
                "api_input_tokens": api["api_input_tokens"],
                "api_output_tokens": api["api_output_tokens"],
                "api_cache_read": api["api_cache_read"],
                "api_cache_create": api["api_cache_create"],
                "est_message_tokens": est_message_tokens,
                "wire_message_count": 0,
                "items": [],
                "tokens_by_status": {},
                "count_by_status": {},
                "breakpoint_payload_idx": -1,
                "prev_breakpoint_payload_idx": prev_bp,
                "divergence_payload_idx": -1,
            })
            continue
        payload = dump["messages"]
        context_state = _context_state_from_dump(dump)
        cur_bp = _find_breakpoint(payload)
        divergence = _payload_divergence(prev_payload, payload)

        items = build_items_for_payload(payload, system_prompt, context_state, tc_index,
                                        system_blocks=dump.get("system_blocks"))
        annotate_cache_status(items, cur_bp, prev_bp, divergence)

        loop_user = next((m for m in reversed(payload) if m.get("role") == "user"), None)
        loop_user_text = message_text(loop_user) if loop_user else ""
        tokens_by_status, count_by_status = _summarize_items(items)

        calls.append({
            "turn": turn,
            "timestamp": timestamp,
            "user_prompt": loop_user_text[:300],
            "api_input_tokens": api["api_input_tokens"],
            "api_output_tokens": api["api_output_tokens"],
            "api_cache_read": api["api_cache_read"],
            "api_cache_create": api["api_cache_create"],
            "est_message_tokens": est_message_tokens,
            "wire_message_count": len(payload),
            "items": items,
            "tokens_by_status": tokens_by_status,
            "count_by_status": count_by_status,
            "breakpoint_payload_idx": cur_bp,
            "prev_breakpoint_payload_idx": prev_bp,
            "divergence_payload_idx": divergence,
        })
        prev_payload = payload
        prev_bp = cur_bp

    return {
        "session_id": data.get("session_id", "?"),
        "model": _resolve_model(session_path, data.get("model") or "") or "?",
        "saved_at": data.get("saved_at", "?"),
        "first_message": data.get("first_message", ""),
        "system_prompt_tokens": estimate_tokens(system_prompt),
        "calls": calls,
    }
