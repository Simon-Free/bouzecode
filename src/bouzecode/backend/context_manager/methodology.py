# [desc] Methodology + Snippet tools: persistent working memory and frozen file regions. [/desc]
"""Methodology stores everything the model needs across turns (append-only).

- ``Methodology(content)`` — appends text to the methodology note.
- ``Snippet(file_path, ranges, label)`` — freeze labeled file ranges into the
  same note (always appends; resolved at save time).

Both write to ``context_state.notes[METHODOLOGY_NOTE]``, cached at the system-block
level. Tool_results vanish at the next iteration, so the model must move what
it needs into here before then.
"""
from __future__ import annotations

import re
import time

from .state import ContextState, METHODOLOGY_NOTE, resolve_context_state
from .compact_methodology import maybe_compact


_USER_BLOCK_RE = re.compile(r"(^## User(?:\s+@[^\n]*)?\n.*?)(?=\n## |\Z)", re.DOTALL | re.MULTILINE)
_METHODOLOGY_HEADER = (
    "[METHODOLOGY — your persistent working memory across turns]\n"
    "Lines marked `## snippet-stale:` mean the range-snippet above is outdated "
    "(file was edited since snapshot). Use the Edit diff output or re-snapshot "
    "with Snippet(symbol=) for fresh content.\n"
)


def split_methodology_for_cache(methodology_text: str, snapshot: str) -> tuple[str, str]:
    """Return (cached_prefix, new_delta). Empty prefix if snapshot is not a prefix of current."""
    if snapshot and methodology_text.startswith(snapshot):
        return snapshot, methodology_text[len(snapshot):]
    return "", methodology_text


def build_methodology_system_blocks(
    methodology_text: str, snapshot: str, cache_control: dict,
) -> tuple[list[dict], str]:
    """Return (extra_system_blocks, meth_delta_for_message_anchor).

    The note is rendered VERBATIM — never re-resolved or rewritten in place.
    Mutating an already-cached snippet body (e.g. re-resolving a symbol after
    its file was edited) drifts the prompt-cache prefix and forces a full
    cache_create every turn.  Instead, edits append a ``## snippet-stale:``
    marker (see stale_hooks), keeping the cached block append-only.
    """
    if not methodology_text:
        return [], ""
    old_meth, new_meth = split_methodology_for_cache(methodology_text, snapshot)
    text = _METHODOLOGY_HEADER + (old_meth if old_meth else new_meth)
    block = {"type": "text", "text": text, "cache_control": cache_control}
    return [block], (new_meth if old_meth else "")


def _extract_user_blocks(methodology: str) -> str:
    """Return concatenation of every ## User block in the existing methodology."""
    return "\n\n".join(m.group(1).rstrip() for m in _USER_BLOCK_RE.finditer(methodology))


def _append_block(context_state: ContextState | None, block: str) -> None:
    if context_state is None or not block:
        return
    current = context_state.notes.get(METHODOLOGY_NOTE, "")
    joiner = "\n\n" if current else ""
    context_state.notes[METHODOLOGY_NOTE] = (current.rstrip() + joiner + block).strip()


def _split_top_level_blocks(text: str) -> list[str]:
    """Split a methodology note into top-level blocks.

    A block starts at each line beginning with ``## `` (a top-level heading,
    NOT ``### ``). Any preamble before the first ``## `` heading forms the
    first block. Each block is stripped. Invariant preserved by the append
    tools (which strip + join with ``\\n\\n``): ``"\\n\\n".join(blocks) == note``.
    """
    if not text:
        return []
    blocks: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if current:
                blk = "\n".join(current).strip()
                if blk:
                    blocks.append(blk)
            current = [line]
        else:
            current.append(line)
    if current:
        blk = "\n".join(current).strip()
        if blk:
            blocks.append(blk)
    return blocks


def _diff_blocks(prev_note: str, cur_note: str) -> dict:
    """Compute an append-only-aware block delta between two note versions.

    Returns ``{"added": [...], "updated": [], "removed": [...]}``.
    ``updated`` is always empty: a block change is modelled as removed(old)
    + added(new), which keeps the fold reconstruction unambiguous. When the
    surviving common blocks are reordered (typically after a compaction that
    dedups/reorders blocks) we emit a FULL REPLACE (removed=all prev,
    added=all cur) so the fold cannot drift.
    """
    prev_blocks = _split_top_level_blocks(prev_note)
    cur_blocks = _split_top_level_blocks(cur_note)
    # Sequence-based (NOT set-based) so exact-duplicate blocks are preserved.
    # Pure append: cur starts with the full prev sequence -> only the tail is
    # new, nothing removed. Otherwise (reorder/compaction/rewrite): ATOMIC full
    # replace. ``added`` is the WHOLE current note as a SINGLE block (never
    # re-split), so reconstruction reproduces it byte-for-byte regardless of the
    # internal separator (compaction joins blocks with '\n', not '\n\n').
    if cur_blocks[: len(prev_blocks)] == prev_blocks:
        return {"added": cur_blocks[len(prev_blocks):], "updated": [], "removed": []}
    return {"added": [cur_note], "updated": [], "removed": list(prev_blocks)}


def reconstruct_methodology_from_timeline(timeline: list[dict]) -> str:
    """Rebuild the current methodology note by folding the per-turn deltas.

    This is the dynamic reconstruction of the block sent to the model: replay
    each turn's delta in order (drop ``removed`` blocks, then append ``added``
    blocks). Robust to compaction because a compaction is journalled as a
    ``removed`` delta (and, on reorder, a full replace). The invariant is
    ``reconstruct_methodology_from_timeline(state.notes_timeline)`` equals the
    live ``notes[METHODOLOGY_NOTE]``.
    """
    blocks: list[str] = []
    for entry in timeline:
        delta = entry.get("delta")
        if delta is None:
            # ENTRÉE HÉRITÉE : les sessions écrites avant le passage au delta pur ne
            # portent qu'un instantané complet des notes. On la traite comme un
            # remplacement total — c'est exactement ce qu'elle décrit. Sans ce repli, une
            # vieille session rechargée (`session_pick`) donnerait une reconstruction VIDE,
            # et le delta du tour suivant serait calculé contre du néant.
            note = entry.get("notes") or ""
            if isinstance(note, dict):  # plus ancien encore : notes stockées en dict
                note = note.get(METHODOLOGY_NOTE, "")
            # Un SEUL bloc, pas un redécoupage. Le repli rejoint avec `\n\n` : redécouper une
            # note dont les séparateurs sont irréguliers (une compaction joint avec `\n`) la
            # normalise, et la reconstruction s'écarte de l'original de quelques caractères.
            # C'est ce qui avait fait écarter 1 433 sessions sur 4 175 à la migration — le
            # contrôle de non-perte refusant, à juste titre, de réécrire un fichier qu'il ne
            # savait pas reproduire à l'identique. Même parti pris que `_diff_blocks` pour un
            # remplacement complet : garder le texte VERBATIM.
            blocks = [str(note)] if note else blocks
            continue
        removed = delta.get("removed") or []
        added = delta.get("added") or []
        if removed:
            # Non-empty removed == an ATOMIC full replace for this turn (reorder
            # / compaction / rewrite): ``added`` holds the whole new note as a
            # single block, so reset to exactly it.
            blocks = list(added)
        else:
            # Pure append: extend, preserving exact-duplicate blocks.
            blocks.extend(added)
    return "\n\n".join(blocks)


def _record_timeline(config: dict, context_state: ContextState) -> None:
    """Append a dated per-turn entry to the notes timeline — LE DELTA SEUL.

    MUST be called AFTER ``maybe_compact`` so that blocks purged by a compaction show up as
    ``removed`` in this turn's delta, keeping the reconstruction invariant intact.

    PLUS D'INSTANTANÉ COMPLET. Chaque entrée portait aussi `notes` : la totalité de la note à
    ce tour. Le journal grossissait donc en O(tours²) — mesuré sur une session de 270 tours,
    384 copies d'une note dont l'état final fait 248 Ko, soit **55 Mo pour ce seul champ**, la
    moitié d'un JSON de session de 113 Mo. L'instantané n'était gardé que « pour le
    constructeur du visualiseur de contexte » : ce consommateur ne le lit plus (il lit les
    notes des dumps `debug_payloads`), et `context_diag` ne lit que `delta`. Le seul lecteur
    restant était CETTE fonction, pour calculer le delta suivant — d'où le repli du journal,
    qui rend exactement la même chose au titre de l'invariant documenté sur
    `reconstruct_methodology_from_timeline`.

    Le contenu d'un tour reste donc entièrement reconstituable, mais il se RECALCULE au lieu
    d'être recopié.
    """
    state = config.get("_state")
    if state is None or not hasattr(state, "notes_timeline"):
        return
    timeline = state.notes_timeline
    prev_note = reconstruct_methodology_from_timeline(timeline)
    cur_note = context_state.notes.get(METHODOLOGY_NOTE, "")
    timeline.append({
        "turn": getattr(state, "turn_count", 0),
        "timestamp": time.time(),
        "delta": _diff_blocks(prev_note, cur_note),
    })


def methodology_tool(params: dict, config: dict) -> str:
    context_state: ContextState | None = resolve_context_state(config)
    if context_state is None:
        return "Error: no context state available"

    content = (params.get("content") or "").rstrip()
    current = context_state.notes.get(METHODOLOGY_NOTE, "")
    joiner = "\n\n" if current and content else ""
    updated = (current.rstrip() + joiner + content).strip()

    context_state.notes[METHODOLOGY_NOTE] = updated
    removed = maybe_compact(context_state, METHODOLOGY_NOTE, config)
    _record_timeline(config, context_state)
    final_size = len(context_state.notes[METHODOLOGY_NOTE])
    msg = f"methodology append: now {final_size} chars"
    if removed:
        msg += f" (compacted: -{removed} chars)"
    return msg


def _prefix_note(result: str, note: str) -> str:
    """Put a repair note ABOVE the result so the model reads it before the outcome."""
    return f"{note}\n{result}" if note else result


def _resolve_snippet_block(
    file_path: str, tool_id: str, ranges: list, label: str, messages: list | None,
) -> tuple[str | None, str]:
    """Render the snippet block for an explicit set of ranges, or refuse."""
    from .snippet_input import dead_tool_id_error
    from .snippet_resolve import (
        find_tool_result_content, list_tool_result_ids, resolve_snippet,
        resolve_snippet_from_result,
    )
    if tool_id:
        content = find_tool_result_content(messages, tool_id)
        if content is None:
            return None, dead_tool_id_error(tool_id, list_tool_result_ids(messages))
        return resolve_snippet_from_result(content, ranges, label, tool_id).strip(), ""
    return resolve_snippet(file_path, ranges, label).strip(), ""


def snippet_tool(params: dict, config: dict) -> str:
    """Freeze labeled file region(s) into the methodology note (append-only)."""
    context_state: ContextState | None = resolve_context_state(config)
    if context_state is None:
        return "Error: no context state available"

    from .snippet_input import infer_ranges, repair_snippet_target
    repair_note = repair_snippet_target(params)

    file_path = params.get("file_path") or ""
    tool_id = params.get("tool_id") or ""
    symbol = params.get("symbol") or ""
    ranges = params.get("ranges") or []
    label = params.get("label") or ""
    discard = params.get("discard", False)

    target = file_path or tool_id or "(no target)"
    state = config.get("_state")
    messages = getattr(state, "messages", None) if state is not None else None

    # Explicit discard: acknowledge without saving anything (ranges takes precedence)
    if discard and not ranges and not symbol:
        return _prefix_note(f"snippet discarded: {target} — explicitly not saved", repair_note)

    if not file_path and not tool_id:
        return _prefix_note(
            "Error: provide 'file_path' (absolute path) or 'tool_id' (a tool_call id)",
            repair_note)

    implicit_note = ""
    # Symbol-based snippet: dynamic resolution, no ranges required
    if symbol:
        if not file_path:
            return _prefix_note(
                "Error: 'symbol' requires 'file_path' (absolute path to the source file)",
                repair_note)
        from .snippet_resolve import resolve_snippet_symbol
        block = resolve_snippet_symbol(file_path, symbol, label).strip()
    else:
        if not isinstance(ranges, list) or not ranges:
            # `ranges` absent is never malformed input — the model named what it
            # wanted and skipped the line numbers. Measure the source and either
            # save a superset of it, or refuse OUT LOUD. Never a silent discard.
            ranges, implicit_note = infer_ranges(file_path, tool_id, target, label, messages)
            if ranges is None:
                return _prefix_note(implicit_note, repair_note)
        block, refusal = _resolve_snippet_block(file_path, tool_id, ranges, label, messages)
        if block is None:
            return _prefix_note(refusal, repair_note)
    if not block:
        return _prefix_note("Error: snippet resolved to empty content", repair_note)

    _append_block(context_state, block)
    removed = maybe_compact(context_state, METHODOLOGY_NOTE, config)
    _record_timeline(config, context_state)
    note_size = len(context_state.notes[METHODOLOGY_NOTE])
    compact_suffix = f" (compacted: -{removed} chars)" if removed else ""
    if "snippet ERROR" in block:
        return _prefix_note(
            f"snippet ERROR captured into methodology (now {note_size} chars){compact_suffix}",
            repair_note)
    if symbol:
        what = f"symbol '{symbol}' from {file_path}"
    elif implicit_note:
        what = implicit_note
    else:
        what = f"{len(ranges)} range(s) from {target}"
    result = f"snippet appended: {what} (methodology now {note_size} chars){compact_suffix}"
    if "(auto-resolved from " in block:
        result += "\nNOTE: snippet auto-resolved from a path that did not exist — check the snippet header and update your next calls."
    return _prefix_note(result, repair_note)


def append_user_msg_to_methodology(context_state: ContextState, user_text: str) -> None:
    """Auto-append a ## User block. Called on every user message (repl + web)."""
    if not user_text:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_block(context_state, f"## User @{ts}\n{user_text.strip()}\n")


def append_plan_to_methodology(context_state: ContextState, plan_content: str) -> None:
    """Auto-append a ## Plan block on WritePlan."""
    if not plan_content or not plan_content.strip():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_block(context_state, f"## Plan @{ts}\n{plan_content.strip()}\n")


def append_overflow_summary_to_methodology(
    context_state: ContextState, summary: str,
) -> None:
    """Persist the summary of an overflowed (auto-cut) thinking block.

    The raw thinking is dropped from the wire next turn; writing its summary
    into the methodology makes the reasoning durable working memory instead of
    a one-shot nudge that survives a single turn."""
    if not summary or not summary.strip():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_block(
        context_state,
        f"## Auto-compacted thoughts after overflow @{ts}\n{summary.strip()}\n",
    )


def append_ask_user_question_to_methodology(
    context_state: ContextState, question: str, answer: str,
) -> None:
    """Auto-append a ## Q&A block when an AskUserQuestion is answered."""
    if not question:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_block(
        context_state,
        f"## Q&A @{ts}\n**Q:** {question.strip()}\n**A:** {(answer or '').strip()}\n",
    )
