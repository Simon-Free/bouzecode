# [desc] Multi-turn methodology cache pipeline tests verifying delta splits and byte-stable system blocks
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Multi-turn methodology cache pipeline tests verifying delta splits and byte-stable system blocks</param></tool_use> [/desc]
"""Simulate multi-turn dispatch to verify the A+B methodology cache pipeline.

Each simulated turn:
  1. compute (system_blocks, meth_delta) the way dispatch.stream() does
  2. advance context_state._methodology_cache_snapshot to the current methodology
After each turn, assertions check:
  - old_meth (system block) stays byte-stable when methodology is idle
  - new delta (meth_delta) contains only the content appended since last snapshot
  - meth_delta is correctly fused into the previous-loop message anchor with
    a cache_control breakpoint by messages_to_anthropic.
"""
from __future__ import annotations

from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from bouzecode.backend.context_manager.methodology import (
    append_ask_user_question_to_methodology,
    append_plan_to_methodology,
    append_user_msg_to_methodology,
    build_methodology_system_blocks,
    methodology_tool,
)
from bouzecode.backend.agent.providers.conversion import messages_to_anthropic


_CC = {"type": "ephemeral"}
_HEADER = "[METHODOLOGY — your persistent working memory across turns]\n"


def _simulate_dispatch_update(context_state, cache_control=_CC):
    """Return (blocks, delta) the way dispatch.stream() would, then advance snapshot."""
    meth = context_state.notes.get(METHODOLOGY_NOTE, "") or ""
    snapshot = getattr(context_state, "_methodology_cache_snapshot", "")
    blocks, delta = build_methodology_system_blocks(meth, snapshot, cache_control)
    if meth:
        context_state._methodology_cache_snapshot = meth
    return blocks, delta


# --- Multi-turn snapshot advancement ----------------------------------------

def test_snapshot_advances_after_each_dispatch():
    gc = ContextState()
    gc.notes[METHODOLOGY_NOTE] = "A"
    b1, d1 = _simulate_dispatch_update(gc)
    assert b1[0]["text"] == _HEADER + "A"
    assert d1 == ""
    assert gc._methodology_cache_snapshot == "A"

    gc.notes[METHODOLOGY_NOTE] = "A" + "B"
    b2, d2 = _simulate_dispatch_update(gc)
    assert b2[0]["text"] == _HEADER + "A", "old_meth must stay byte-stable at 'A'"
    assert d2 == "B", "new delta must be 'B'"
    assert gc._methodology_cache_snapshot == "AB"

    gc.notes[METHODOLOGY_NOTE] = "AB"
    b3, d3 = _simulate_dispatch_update(gc)
    assert b3[0]["text"] == _HEADER + "AB", "old_meth must now be 'AB' (full) and cache-read"
    assert d3 == ""

    gc.notes[METHODOLOGY_NOTE] = "AB" + "C"
    b4, d4 = _simulate_dispatch_update(gc)
    assert b4[0]["text"] == _HEADER + "AB"
    assert d4 == "C"


def test_system_block_bytes_stable_across_idle_turns():
    gc = ContextState()
    gc.notes[METHODOLOGY_NOTE] = "X"
    b1, _ = _simulate_dispatch_update(gc)
    b2, _ = _simulate_dispatch_update(gc)
    b3, _ = _simulate_dispatch_update(gc)
    assert b1[0]["text"] == b2[0]["text"] == b3[0]["text"]


def test_replace_mode_now_appends():
    """mode='replace' was removed — methodology_tool always appends now."""
    gc = ContextState()
    append_user_msg_to_methodology(gc, "hi")
    _simulate_dispatch_update(gc)
    snap = gc._methodology_cache_snapshot

    methodology_tool({"mode": "replace", "content": "## new plan\n"}, {"_context_state": gc})
    new_full = gc.notes[METHODOLOGY_NOTE]
    assert "## new plan" in new_full
    # Content is appended, snapshot still a prefix
    assert new_full.startswith(snap.rstrip())


# --- Auto-append flows all produce a clean split ----------------------------

def test_user_msg_append_produces_clean_split():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "first question")
    _simulate_dispatch_update(gc)
    snap_after_t1 = gc._methodology_cache_snapshot

    append_user_msg_to_methodology(gc, "second question")
    blocks, delta = _simulate_dispatch_update(gc)
    assert blocks[0]["text"] == _HEADER + snap_after_t1
    assert "second question" in delta
    assert "first question" not in delta


def test_plan_append_produces_clean_split():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "question")
    _simulate_dispatch_update(gc)
    snap = gc._methodology_cache_snapshot

    append_plan_to_methodology(gc, "1. do X\n2. do Y")
    blocks, delta = _simulate_dispatch_update(gc)
    assert blocks[0]["text"] == _HEADER + snap
    assert "## Plan" in delta and "do X" in delta


def test_askuserquestion_append_produces_clean_split():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "question")
    _simulate_dispatch_update(gc)
    snap = gc._methodology_cache_snapshot

    append_ask_user_question_to_methodology(gc, "which file?", "foo.py")
    blocks, delta = _simulate_dispatch_update(gc)
    assert blocks[0]["text"] == _HEADER + snap
    assert "## Q&A" in delta and "which file?" in delta and "foo.py" in delta


def test_methodology_tool_append_produces_clean_split():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "q1")
    _simulate_dispatch_update(gc)
    snap = gc._methodology_cache_snapshot

    methodology_tool({"content": "## observation\nfoo is bar"}, {"_context_state": gc})
    blocks, delta = _simulate_dispatch_update(gc)
    assert blocks[0]["text"] == _HEADER + snap
    assert "## observation" in delta and "foo is bar" in delta


def test_mixed_appends_across_turns_accumulate():
    gc = ContextState()
    append_user_msg_to_methodology(gc, "q1")
    _simulate_dispatch_update(gc)

    methodology_tool({"content": "obs A"}, {"_context_state": gc})
    _, d = _simulate_dispatch_update(gc)
    assert "obs A" in d
    assert "q1" not in d

    append_plan_to_methodology(gc, "plan X")
    append_ask_user_question_to_methodology(gc, "path?", "/tmp")
    _, d = _simulate_dispatch_update(gc)
    assert "plan X" in d
    assert "/tmp" in d
    assert "obs A" not in d, "obs A was cached at previous turn, belongs to old_meth now"


# --- Integration with messages_to_anthropic: previous-loop anchor breakpoint

def _msgs_turn1_complete_then_turn2():
    return [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer", "tool_calls": []},
        {"role": "user", "content": "second question"},
    ]


def test_places_breakpoint_on_previous_loop_anchor():
    """cache_last places an ephemeral breakpoint on the previous loop's last
    message, with no methodology delta leaking into the anchor text."""
    msgs = _msgs_turn1_complete_then_turn2()
    payload = messages_to_anthropic(msgs, cache_last=True)
    anchor = payload[1]
    assert isinstance(anchor["content"], list)
    assert anchor["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert anchor["content"][0]["text"] == "first answer"


# --- Single-block invariant: every append flavor goes into ONE old_meth + ONE delta

def test_all_append_flavors_merge_into_single_old_block_and_single_delta():
    """User msg + plan + Q&A + Methodology tool between two turns must all land
    in the SAME new_meth delta (not separate blocks), so we stay at 1 old block
    + 1 delta regardless of how many sources appended."""
    gc = ContextState()
    append_user_msg_to_methodology(gc, "q1")
    _simulate_dispatch_update(gc)
    snap = gc._methodology_cache_snapshot

    append_user_msg_to_methodology(gc, "q2")
    append_plan_to_methodology(gc, "step A")
    append_ask_user_question_to_methodology(gc, "?", "!")
    methodology_tool({"content": "observation Z"}, {"_context_state": gc})

    blocks, delta = _simulate_dispatch_update(gc)
    assert len(blocks) == 1, "old methodology must always be ONE block"
    assert blocks[0]["text"] == _HEADER + snap
    assert "q2" in delta
    assert "step A" in delta
    assert "## Q&A" in delta
    assert "observation Z" in delta
    assert delta.count(_HEADER) == 0, "delta must NOT repeat the methodology header"
