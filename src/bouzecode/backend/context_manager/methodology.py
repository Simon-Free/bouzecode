# [desc] Methodology + Snippet tools: persistent working memory and frozen file regions. [/desc]
"""Methodology stores everything the model needs across turns (append-only).

- ``Methodology(content)`` — appends text to the methodology note.
- ``Snippet(file_path, ranges, label)`` — freeze labeled file ranges into the
  same note (always appends; resolved at save time).

Both write to ``gc_state.notes[METHODOLOGY_NOTE]``, cached at the system-block
level. Tool_results vanish at the next iteration, so the model must move what
it needs into here before then.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .state import GCState, METHODOLOGY_NOTE, resolve_context_state
from .compact_methodology import maybe_compact


_USER_BLOCK_RE = re.compile(r"(^## User(?:\s+@[^\n]*)?\n.*?)(?=\n## |\Z)", re.DOTALL | re.MULTILINE)
_METHODOLOGY_HEADER = "[METHODOLOGY — your persistent working memory across turns]\n"


def split_methodology_for_cache(methodology_text: str, snapshot: str) -> tuple[str, str]:
    """Return (cached_prefix, new_delta). Empty prefix if snapshot is not a prefix of current."""
    if snapshot and methodology_text.startswith(snapshot):
        return snapshot, methodology_text[len(snapshot):]
    return "", methodology_text


def build_methodology_system_blocks(
    methodology_text: str, snapshot: str, cache_control: dict,
) -> tuple[list[dict], str]:
    """Return (extra_system_blocks, meth_delta_for_message_anchor).

    Symbol-based snippets (``## snippet: <path> :: <symbol>``) are re-resolved
    BEFORE the cache split so their bodies stay current.  The methodology text
    is only mutated when the source file actually changed, preserving the
    prefix-cache hit rate.
    """
    if not methodology_text:
        return [], ""
    from .snippet_resolve import refresh_symbol_snippets
    methodology_text = refresh_symbol_snippets(methodology_text)
    old_meth, new_meth = split_methodology_for_cache(methodology_text, snapshot)
    text = _METHODOLOGY_HEADER + (old_meth if old_meth else new_meth)
    block = {"type": "text", "text": text, "cache_control": cache_control}
    return [block], (new_meth if old_meth else "")


def _resolve_snippet(file_path: str, ranges: list, label: str) -> str:
    """Read the file and return labeled line ranges as a markdown block."""
    path = Path(file_path)
    if not path.is_absolute():
        return f"\n## snippet ERROR: {file_path} — path must be absolute\n"
    resolution_note = ""
    if not path.exists():
        from ..tools.state import find_closest_read_file, list_read_files_with_basename
        fallback = find_closest_read_file(file_path)
        if fallback is None:
            candidates = list_read_files_with_basename(path.name)
            if len(candidates) > 1:
                joined = "\n  - ".join(candidates)
                return (
                    f"\n## snippet ERROR: {file_path} — file not found; "
                    f"multiple read files share this basename (ambiguous):\n  - {joined}\n"
                )
            return f"\n## snippet ERROR: {file_path} — file not found\n"
        resolution_note = f" (auto-resolved from {file_path})"
        path = Path(fallback)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for rng in ranges or []:
        if not isinstance(rng, list) or len(rng) != 2:
            out.append(f"## snippet ERROR: {file_path} — invalid range {rng!r}\n")
            continue
        start, end = rng
        if start < 1:
            start = 1
        if end > len(lines):
            end = len(lines)
        if start > end:
            out.append(f"## snippet ERROR: {file_path} L{rng[0]}-{rng[1]} — empty range\n")
            continue
        suffix = f' — "{label}"' if label else ""
        body = "\n".join(f"{i:>5}  {lines[i-1]}" for i in range(start, end + 1))
        out.append(f"## snippet: {path} L{start}-{end}{suffix}{resolution_note}\n{body}\n")
    return "\n" + "\n".join(out)


def _extract_user_blocks(methodology: str) -> str:
    """Return concatenation of every ## User block in the existing methodology."""
    return "\n\n".join(m.group(1).rstrip() for m in _USER_BLOCK_RE.finditer(methodology))


def _append_block(gc_state: GCState | None, block: str) -> None:
    if gc_state is None or not block:
        return
    current = gc_state.notes.get(METHODOLOGY_NOTE, "")
    joiner = "\n\n" if current else ""
    gc_state.notes[METHODOLOGY_NOTE] = (current.rstrip() + joiner + block).strip()


def _record_timeline(config: dict, gc_state: GCState) -> None:
    state = config.get("_state")
    if state is None or not hasattr(state, "notes_timeline"):
        return
    state.notes_timeline.append({
        "turn": getattr(state, "turn_count", 0),
        "timestamp": time.time(),
        "notes": dict(gc_state.notes),
    })


def methodology_tool(params: dict, config: dict) -> str:
    gc_state: GCState | None = resolve_context_state(config)
    if gc_state is None:
        return "Error: no GC state available"

    content = (params.get("content") or "").rstrip()
    current = gc_state.notes.get(METHODOLOGY_NOTE, "")
    joiner = "\n\n" if current and content else ""
    updated = (current.rstrip() + joiner + content).strip()

    gc_state.notes[METHODOLOGY_NOTE] = updated
    _record_timeline(config, gc_state)
    removed = maybe_compact(gc_state, METHODOLOGY_NOTE)
    final_size = len(gc_state.notes[METHODOLOGY_NOTE])
    msg = f"methodology append: now {final_size} chars"
    if removed:
        msg += f" (compacted: -{removed} chars)"
    return msg


def snippet_tool(params: dict, config: dict) -> str:
    """Freeze labeled file region(s) into the methodology note (append-only)."""
    gc_state: GCState | None = resolve_context_state(config)
    if gc_state is None:
        return "Error: no GC state available"

    file_path = params.get("file_path") or ""
    tool_id = params.get("tool_id") or ""
    symbol = params.get("symbol") or ""
    ranges = params.get("ranges") or []
    label = params.get("label") or ""
    discard = params.get("discard", False)

    target = file_path or tool_id or "(no target)"

    # Explicit discard: acknowledge without saving anything (ranges takes precedence)
    if discard and not ranges and not symbol:
        return f"snippet discarded: {target} — explicitly not saved"

    if not file_path and not tool_id:
        return "Error: provide 'file_path' (absolute path) or 'tool_id' (a tool_call id)"

    # Symbol-based snippet: dynamic resolution, no ranges required
    if symbol:
        if not file_path:
            return "Error: 'symbol' requires 'file_path' (absolute path to the source file)"
        from .snippet_resolve import resolve_snippet_symbol
        block = resolve_snippet_symbol(file_path, symbol, label).strip()
    elif not isinstance(ranges, list) or not ranges:
        return ("Error: 'ranges' must be a non-empty JSON array of [start, end] pairs. "
                'Example: <param name="ranges">[[10, 25], [40, 60]]</param>')
    elif tool_id:
        from .snippet_resolve import find_tool_result_content, resolve_snippet_from_result
        state = config.get("_state")
        messages = getattr(state, "messages", None) if state is not None else None
        content = find_tool_result_content(messages, tool_id)
        if content is None:
            return f"Error: no tool_result found for tool_id '{tool_id}'"
        block = resolve_snippet_from_result(content, ranges, label, tool_id).strip()
    else:
        block = _resolve_snippet(file_path, ranges, label).strip()
    if not block:
        return "Error: snippet resolved to empty content"

    _append_block(gc_state, block)
    _record_timeline(config, gc_state)

    removed = maybe_compact(gc_state, METHODOLOGY_NOTE)
    note_size = len(gc_state.notes[METHODOLOGY_NOTE])
    compact_suffix = f" (compacted: -{removed} chars)" if removed else ""
    if "snippet ERROR" in block:
        return f"snippet ERROR captured into methodology (now {note_size} chars){compact_suffix}"
    if symbol:
        result = f"snippet appended: symbol '{symbol}' from {file_path} (methodology now {note_size} chars){compact_suffix}"
    else:
        result = f"snippet appended: {len(ranges)} range(s) from {target} (methodology now {note_size} chars){compact_suffix}"
    if "(auto-resolved from " in block:
        result += "\nNOTE: snippet auto-resolved from a path that did not exist — check the snippet header and update your next calls."
    return result


def append_user_msg_to_methodology(gc_state: GCState, user_text: str) -> None:
    """Auto-append a ## User block. Called on every user message (repl + web)."""
    if not user_text:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_block(gc_state, f"## User @{ts}\n{user_text.strip()}\n")


def append_plan_to_methodology(gc_state: GCState, plan_content: str) -> None:
    """Auto-append a ## Plan block on WritePlan."""
    if not plan_content or not plan_content.strip():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_block(gc_state, f"## Plan @{ts}\n{plan_content.strip()}\n")


def append_ask_user_question_to_methodology(
    gc_state: GCState, question: str, answer: str,
) -> None:
    """Auto-append a ## Q&A block when an AskUserQuestion is answered."""
    if not question:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_block(
        gc_state,
        f"## Q&A @{ts}\n**Q:** {question.strip()}\n**A:** {(answer or '').strip()}\n",
    )
