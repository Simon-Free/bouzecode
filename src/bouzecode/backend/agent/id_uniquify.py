# [desc] Rewrite assistant tool_call ids on ingest so they never collide with prior ids in the message history. [/desc]
"""Prevent tool_call_id collisions across turns.

The model picks short ids (e.g. `r1`, `w2`) per the XML tool protocol and
reuses them freely across turns. If the incoming id matches any id already
present in `state.messages`, the wire ends up with two distinct tool_calls
sharing one id — confusing both the model and downstream tooling.

The safe fix is to uniquify the id on ingest. We rewrite it to
`t{turn}_{original}` (with a numeric suffix if that still clashes). Same-turn
`depends_on` references are rewritten in lockstep so the DAG resolves correctly.
"""
from __future__ import annotations


def _collect_used_ids(state) -> set[str]:
    used: set[str] = set()
    for msg in state.messages:
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                tid = tc.get("id")
                if tid:
                    used.add(tid)
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if tid:
                used.add(tid)
    return used


def _pick_fresh_id(original: str, turn: int, used: set[str]) -> str:
    candidate = f"t{turn}_{original}"
    if candidate not in used:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in used:
        suffix += 1
    return f"{candidate}_{suffix}"


def uniquify_tool_call_ids(tool_calls: list, state) -> dict[str, str]:
    """Rewrite colliding tool_call ids in-place and rewrite same-turn depends_on refs.

    Only ids that already exist in state.messages or gc_state.trashed_ids are
    remapped. Ids the model has never used before pass through unchanged,
    preserving behavior for simple sessions and existing tests."""
    if not tool_calls:
        return {}
    used = _collect_used_ids(state)
    remap: dict[str, str] = {}
    for tc in tool_calls:
        original = tc.get("id")
        if not original or original not in used:
            if original:
                used.add(original)
            continue
        fresh = _pick_fresh_id(original, state.turn_count, used)
        remap[original] = fresh
        tc["id"] = fresh
        used.add(fresh)

    if not remap:
        return {}
    from .dag import _coerce_list
    for tc in tool_calls:
        params = tc.get("input") or {}
        deps = _coerce_list(params.get("depends_on"))
        if deps:
            params["depends_on"] = [remap.get(d, d) for d in deps]
    return remap
