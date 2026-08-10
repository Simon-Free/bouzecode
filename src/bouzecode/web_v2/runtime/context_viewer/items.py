# [desc] Context item builders: message -> items conversion, system/notes/assistant/tool_result items, cache-status annotation. Token primitives live in _tokens.py (re-exported here for compat). [/desc]
"""Per-item builders. Pure token/brief primitives are in _tokens.py and re-exported below for backward-compatible imports (`from .items import estimate_tokens`, etc.)."""
from ._tokens import (  # noqa: F401 — re-exported for backward-compatible imports
    _PREFERRED_KEYS,
    TOKEN_DIVISOR,
    estimate_tokens,
    message_text,
    tool_call_brief,
    serialize_tool_call,
    build_tool_call_index,
)


def _system_item(system_prompt: str) -> dict:
    return {
        "kind": "system", "label": "System prompt + tool docs",
        "est_tokens": estimate_tokens(system_prompt),
        "preview": system_prompt[:300], "text": system_prompt, "gc_status": "stable",
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
        "preview": notes_text[:400], "text": notes_text, "gc_status": "live",
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
        "preview": briefs[:400], "text": payload, "gc_status": gc_status, "n_tools": len(tool_calls),
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
        "preview": text[:400], "text": text, "gc_status": gc_status,
        "tool_call_id": call_id, "tool_name": name,
    }


def _extract_block_text(block) -> str:
    """Local copy of session_analysis._extract_text (pure, no backend.agent
    import → avoids a heavy import cascade that crashes under a patched
    CONFIG_DIR). Handles str / {type:text,text} / {content}/{text} / list."""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        if block.get("type") == "text":
            return block.get("text", "")
        return block.get("content", "") or block.get("text", "")
    if isinstance(block, list):
        return "\n".join(_extract_block_text(b) for b in block)
    return str(block)


def _has_cc(block) -> bool:
    """A system block with a cache_control marker is (written to / served from)
    the prefix cache. Pure, no backend.agent import."""
    return isinstance(block, dict) and "cache_control" in block


def _system_block_items(system_blocks: list) -> list[dict]:
    """Build one context item per REAL wire system block (source of truth for
    what Anthropic actually caches). A block carrying a `cache_control` marker
    is served from / written to the prefix cache → cache_status="cached"; a
    block without it (e.g. the volatile Session Context) is fresh every turn.

    This replaces the single synthetic `_system_item` when the turn dump
    captured `system_blocks` (normal web turns). Falls back to `_system_item`
    when absent (old runs / stream-interrupted turns without system_blocks)."""
    items: list[dict] = []
    for block in system_blocks:
        text = _extract_block_text(block)
        if not text:
            continue
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        label = first_line[:80] or "System block"
        items.append({
            "kind": "system_block",
            "label": label,
            "est_tokens": estimate_tokens(text),
            "preview": text[:400],
            "text": text,
            "gc_status": "stable",
            "payload_idx": None,
            "cache_status": "cached" if _has_cc(block) else "fresh",
        })
    return items


def build_items_for_payload(
    payload: list[dict], system_prompt: str, context_state, tc_index: dict,
    system_blocks: list | None = None,
) -> list[dict]:
    """Build the flat list of context objects from an already-compacted payload.

    The notes_block is INJECTED into the last user message at dispatch time
    (`providers/backends/dispatch.py:_inject_into_last_user_message`), so we
    show it positioned right BEFORE that user message rather than as a top-
    of-context item.

    When the turn dump captured the REAL wire `system_blocks`, we expose one
    item per block segmented by `cache_control` (the actual cache truth).
    Otherwise we fall back to the single synthetic `_system_item`.
    """
    if system_blocks:
        items: list[dict] = _system_block_items(system_blocks)
    else:
        items = [_system_item(system_prompt or "")]

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
                "est_tokens": estimate_tokens(text), "preview": text[:400], "text": text,
                "gc_status": "live",
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
        if item["kind"] == "system_block":
            # Already classified from the real cache_control marker — keep it.
            continue
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
