# [desc] Replace prior-turn tool_result contents with minimal stubs to shrink follow-up API payloads. [/desc]
"""Follow-up compaction: stub past-turn tool_results before each API call.

Non-destructive: produces a new message list, leaves `state.messages` intact
so persistence and resume keep the full history.
"""
from __future__ import annotations

import json
import time
from typing import Iterable

DEFAULT_EXEMPT_TOOLS = frozenset({"Edit", "Write", "TodoWrite"})


def compact_tool_history(
    messages: list,
    keep_last_n_turns: int = 0,
    exempt_tools: Iterable[str] = DEFAULT_EXEMPT_TOOLS,
) -> list:
    """Return a NEW list where past-turn tool_result contents are replaced by stubs.

    A "turn" begins at a role='user' message. The current turn (from the last
    user message onward) is always kept intact. `keep_last_n_turns` controls
    how many additional complete prior turns retain their full tool results.

    Args:
        messages: full message history (not mutated)
        keep_last_n_turns: count of complete prior turns to keep verbatim (default 0)
        exempt_tools: tool names whose results are never stubbed
    Returns:
        a new list of messages; tool messages outside the protected window
        have their `content` replaced by a one-line stub
    """
    exempt = frozenset(exempt_tools)
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    # Need at least (keep_last_n_turns + 1) user messages to have anything to compact
    if len(user_indices) <= keep_last_n_turns + 1:
        return list(messages)

    cutoff = user_indices[-(keep_last_n_turns + 1)]

    tool_call_lookup = _build_tool_call_lookup(messages)

    compacted = []
    for index, message in enumerate(messages):
        if index >= cutoff or message.get("role") != "tool" or message.get("name") in exempt:
            compacted.append(message)
            continue
        tool_call_id = message.get("tool_call_id", "")
        name, inp = tool_call_lookup.get(
            tool_call_id, (message.get("name", "tool"), {})
        )
        stubbed = dict(message)
        stubbed["content"] = _build_stub(name, inp)
        compacted.append(stubbed)
    return compacted


def _build_tool_call_lookup(messages: list) -> dict:
    """Map tool_call_id -> (name, input) by walking assistant.tool_calls."""
    lookup: dict = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            lookup[tool_call.get("id", "")] = (
                tool_call.get("name", ""),
                tool_call.get("input") or {},
            )
    return lookup


def _build_stub(name: str, input_dict: dict) -> str:
    """Render a one-line stub describing a past tool call whose output is elided."""
    brief = _input_brief(name, input_dict)
    return f"[{name}({brief}) — output elided on follow-up]"


def _input_brief(name: str, inp: dict) -> str:
    if name == "Read":
        path = inp.get("file_path", "?")
        parts = [f"file_path={path}"]
        if "offset" in inp:
            parts.append(f"offset={inp['offset']}")
        if "limit" in inp:
            parts.append(f"limit={inp['limit']}")
        return ", ".join(parts)
    if name == "Bash":
        cmd = (inp.get("command") or "").replace("\n", " ")
        if len(cmd) > 100:
            cmd = cmd[:97] + "..."
        return f"command={cmd!r}"
    if name == "Grep":
        parts = [f"pattern={inp.get('pattern', '?')!r}"]
        if "path" in inp:
            parts.append(f"path={inp['path']}")
        return ", ".join(parts)
    if name == "Glob":
        return f"pattern={inp.get('pattern', '?')!r}"
    try:
        rendered = json.dumps(inp, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered = str(inp)
    if len(rendered) > 120:
        rendered = rendered[:117] + "..."
    return rendered


def build_messages_for_api(state, config: dict) -> list:
    """Apply follow-up compaction + model-driven GC, then inject working memory notes."""
    if not config.get("followup_compaction_enabled", True):
        compacted = list(state.messages)
    else:
        keep = config.get("followup_keep_last_n_turns", 0)
        exempt = config.get("followup_exempt_tools", DEFAULT_EXEMPT_TOOLS)
        compacted = compact_tool_history(state.messages, keep_last_n_turns=keep, exempt_tools=exempt)

        from compaction import estimate_tokens
        tokens_before = estimate_tokens(state.messages)
        tokens_after = estimate_tokens(compacted)
        if tokens_before != tokens_after:
            state.compaction_log.append({
                "event": "followup_compact",
                "timestamp": time.time(),
                "turn": getattr(state, "turn_count", 0),
                "tokens_est_before": tokens_before,
                "tokens_est_after": tokens_after,
                "tokens_est_saved": tokens_before - tokens_after,
            })

    return _apply_context_gc(compacted, state)


def _apply_context_gc(messages: list, state) -> list:
    """Apply model-driven GC decisions and inject working memory notes."""
    from context_gc import apply_gc, inject_notes
    gc_state = getattr(state, 'gc_state', None)
    if not gc_state:
        return messages
    if not gc_state.trashed_ids and not gc_state.snippets and not gc_state.notes:
        return messages

    from compaction import estimate_tokens
    tokens_before = estimate_tokens(messages)
    result = apply_gc(messages, gc_state)
    result = inject_notes(result, gc_state.notes)
    tokens_after = estimate_tokens(result)
    if tokens_before != tokens_after:
        state.compaction_log.append({
            "event": "context_gc",
            "timestamp": time.time(),
            "turn": getattr(state, "turn_count", 0),
            "trashed_count": len(gc_state.trashed_ids),
            "snippet_count": len(gc_state.snippets),
            "notes_count": len(gc_state.notes),
            "tokens_est_saved": tokens_before - tokens_after,
        })
    return result
