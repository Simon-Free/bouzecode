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

from ...web.context_viewer.items import (
    annotate_cache_status, build_items_for_payload, build_tool_call_index,
    estimate_tokens, message_text,
)


def _load_turn_dumps(session_id: str) -> dict[int, dict]:
    """Return {turn_number: dump_record} or {} if no dump file exists."""
    if not session_id:
        return {}
    from bouzecode.backend.core.config import CONFIG_DIR
    dump_path = Path(CONFIG_DIR) / "debug_payloads" / session_id / "turns.jsonl"
    if not dump_path.exists():
        return {}
    out: dict[int, dict] = {}
    for line in dump_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        out[record["turn"]] = record
    return out


def _context_state_from_dump(raw: dict):
    """Adapt the dumped context_state dict into the ContextState shape we use (notes-only)."""
    return types.SimpleNamespace(notes=raw.get("notes") or {})


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
    if not raw_messages or not log:
        return None

    dumps = _load_turn_dumps(data.get("session_id", ""))
    if not dumps:
        return {
            "session_id": data.get("session_id", "?"),
            "model": data.get("model", "?"),
            "saved_at": data.get("saved_at", "?"),
            "first_message": data.get("first_message", ""),
            "system_prompt_tokens": estimate_tokens(data.get("system_prompt", "")),
            "calls": [],
            "missing_dumps": True,
        }

    system_prompt = data.get("system_prompt", "") or ""
    tc_index = build_tool_call_index(raw_messages)

    calls: list[dict] = []
    prev_payload: list[dict] = []
    prev_bp = -1
    for entry in log:
        turn = entry.get("turn")
        dump = dumps.get(turn)
        if not dump:
            continue
        payload = dump["messages"]
        context_state = _context_state_from_dump(dump.get("context_state") or {})
        cur_bp = _find_breakpoint(payload)
        divergence = _payload_divergence(prev_payload, payload)

        items = build_items_for_payload(payload, system_prompt, context_state, tc_index)
        annotate_cache_status(items, cur_bp, prev_bp, divergence)

        loop_user = next((m for m in reversed(payload) if m.get("role") == "user"), None)
        loop_user_text = message_text(loop_user) if loop_user else ""
        tokens_by_status, count_by_status = _summarize_items(items)

        calls.append({
            "turn": turn,
            "timestamp": entry.get("timestamp"),
            "user_prompt": loop_user_text[:300],
            "api_input_tokens": entry.get("api_input_tokens", 0),
            "api_output_tokens": entry.get("api_output_tokens", 0),
            "api_cache_read": entry.get("api_cache_read", 0),
            "api_cache_create": entry.get("api_cache_create", 0),
            "est_message_tokens": entry.get("est_message_tokens", 0),
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
        "model": data.get("model", "?"),
        "saved_at": data.get("saved_at", "?"),
        "first_message": data.get("first_message", ""),
        "system_prompt_tokens": estimate_tokens(system_prompt),
        "calls": calls,
    }
