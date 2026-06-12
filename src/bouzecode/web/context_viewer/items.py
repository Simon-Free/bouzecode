# [desc] Context item primitives: token estimate, tool-call briefs, message -> items conversion, cache-status annotation. [/desc]
"""Per-item helpers: token estimation, tool_call briefs, items construction."""
import json

_PREFERRED_KEYS = {
    "Read": "file_path", "Edit": "file_path", "Write": "file_path",
    "Bash": "command", "Grep": "pattern", "Glob": "pattern",
    "WebFetch": "url", "WebSearch": "query", "Skill": "name",
    "Snippet": "file_path", "MemorySave": "name", "NotebookEdit": "notebook_path",
    "Agent": "prompt", "GetFolderDescription": "folder_path",
}
TOKEN_DIVISOR = 3.5


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / TOKEN_DIVISOR))


def message_text(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content or ""


def tool_call_brief(name: str, tool_input: dict, max_len: int = 80) -> str:
    key = _PREFERRED_KEYS.get(name)
    value = tool_input.get(key) if key else None
    if value is None:
        for candidate in tool_input.values():
            if isinstance(candidate, str) and candidate:
                value = candidate
                break
    if not value:
        return ""
    value = str(value).replace("\n", " ").strip()
    return value[:max_len - 1] + "\u2026" if len(value) > max_len else value


def serialize_tool_call(tool_call: dict) -> str:
    """Approximate on-wire payload size of a single tool_call."""
    return json.dumps(tool_call.get("input") or {}, ensure_ascii=False) + (tool_call.get("name", "") or "")


def build_tool_call_index(messages: list[dict]) -> dict[str, tuple[str, dict]]:
    """Map tool_call_id -> (tool_name, tool_input) across all assistant turns."""
    index: dict[str, tuple[str, dict]] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            call_id = tc.get("id", "")
            if call_id:
                index[call_id] = (tc.get("name", ""), tc.get("input") or {})
    return index


def _system_item(system_prompt: str) -> dict:
    return {
        "kind": "system", "label": "System prompt + tool docs",
        "est_tokens": estimate_tokens(system_prompt),
        "preview": system_prompt[:300], "gc_status": "stable",
        "payload_idx": None,
    }


def _notes_item(notes: dict[str, str], target_payload_idx: int) -> dict:
    notes_text = "[Your working memory notes]\n" + "\n\n".join(
        f"## {name}\n{content}" for name, content in notes.items()
    ) + "\n[/Notes]"
    return {
        "kind": "notes_block",
        "label": f"Notes block prepended to user msg #{target_payload_idx} ({len(notes)} note(s))",
        "est_tokens": estimate_tokens(notes_text),
        "preview": notes_text[:400], "gc_status": "live",
        "payload_idx": None,
    }


def _assistant_item(msg: dict, text: str, is_old: bool, compact_xml: bool) -> dict:
    tool_calls = msg.get("tool_calls") or []
    payload = text + "".join(serialize_tool_call(tc) for tc in tool_calls)
    tokens = estimate_tokens(payload)
    gc_status = "live"
    if compact_xml and is_old and tool_calls:
        tokens = max(tokens // 4, 20)
        gc_status = "xml-compacted"
    if tool_calls:
        names = ", ".join(tc.get("name", "?") for tc in tool_calls)
        briefs = "; ".join(
            f"{tc.get('name','?')}({tool_call_brief(tc.get('name',''), tc.get('input') or {}, 40)})"
            for tc in tool_calls
        )
        label = f"Asst \u2192 {len(tool_calls)} tools: {names}"
    else:
        label = "Asst text"
        briefs = text[:200]
    return {
        "kind": "assistant", "label": label, "est_tokens": tokens,
        "preview": briefs[:400], "gc_status": gc_status, "n_tools": len(tool_calls),
    }


def _tool_result_item(msg: dict, text: str, tc_index: dict, context_state) -> dict:
    call_id = msg.get("tool_call_id", "")
    name, tool_input = tc_index.get(call_id, ("?", {}))
    if name == "?":
        name = msg.get("name", "?")
    gc_status = "verbatim"
    brief = tool_call_brief(name, tool_input)
    label = f"{name}({brief})" if brief else name
    return {
        "kind": "tool_result", "label": label, "est_tokens": estimate_tokens(text),
        "preview": text[:400], "gc_status": gc_status,
        "tool_call_id": call_id, "tool_name": name,
    }


def build_items_for_payload(
    payload: list[dict], system_prompt: str, context_state, tc_index: dict,
) -> list[dict]:
    """Build the flat list of context objects from an already-compacted payload.

    The notes_block is INJECTED into the last user message at dispatch time
    (`providers/backends/dispatch.py:_inject_into_last_user_message`), so we
    show it positioned right BEFORE that user message rather than as a top-
    of-context item.
    """
    items: list[dict] = [_system_item(system_prompt or "")]

    last_user_idx = max(
        (i for i in range(len(payload)) if payload[i].get("role") == "user"), default=-1,
    )
    notes = context_state.notes

    for i, msg in enumerate(payload):
        role = msg.get("role", "")
        text = message_text(msg)
        if role == "user":
            if i == last_user_idx and notes:
                items.append(_notes_item(notes, i))
            preview = text[:200].replace("\n", " ")
            item = {
                "kind": "user", "label": preview[:80] or "User msg",
                "est_tokens": estimate_tokens(text), "preview": text[:400], "gc_status": "live",
            }
        elif role == "assistant":
            item = _assistant_item(msg, text, i < last_user_idx, False)
        elif role == "tool":
            item = _tool_result_item(msg, text, tc_index, context_state)
        else:
            continue
        item["payload_idx"] = i
        items.append(item)
    return items


def annotate_cache_status(
    items: list[dict], cur_bp_payload_idx: int, prev_bp_payload_idx: int,
    divergence_payload_idx: int,
) -> None:
    """Mark each item cached / new-cache / fresh using its payload index.

    Anthropic's prefix cache hit at this call covers payload positions
    0..min(prev_bp, divergence-1). Positions in (cached_end, cur_bp] are
    newly written to cache. Positions > cur_bp are sent at full price.
    Synthetic items (system, notes_block) have payload_idx=None and are
    classified by kind: system is always cached after call 1, notes_block is
    always fresh (re-injected into the last user msg every iteration).
    """
    cached_end_payload = -1
    if prev_bp_payload_idx >= 0 and divergence_payload_idx >= 0:
        cached_end_payload = min(prev_bp_payload_idx, divergence_payload_idx - 1)

    for item in items:
        if item["kind"] == "system":
            item["cache_status"] = "cached"
            continue
        if item["kind"] == "notes_block":
            item["cache_status"] = "fresh"
            continue
        pi = item.get("payload_idx")
        if pi is None:
            item["cache_status"] = "fresh"
            continue
        if cached_end_payload >= 0 and pi <= cached_end_payload:
            item["cache_status"] = "cached"
        elif cur_bp_payload_idx >= 0 and pi <= cur_bp_payload_idx:
            item["cache_status"] = "new-cache"
        else:
            item["cache_status"] = "fresh"
