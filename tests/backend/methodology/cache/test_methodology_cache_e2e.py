# [desc] E2E diagnostic (real gateway, no LLM mock): fill methodology via every path, run two turns through dispatch.stream, and verify the methodology cache-write becomes a cache-read. Prints exact byte diffs if the cache fails. [/desc]
"""E2E diagnostic for the "methodology cache-write never hits" complaint.

Wraps ``stream_anthropic`` with a recording pass-through (real API still
serves the request) so we can:
  1. byte-compare the stable_prefix / tool_docs / methodology blocks across
     turns — if any one drifts, that block's cache line is invalidated;
  2. read the post-call ``usage.cache_read_input_tokens`` — turn 2 must
     grow past turn 1's baseline by at least the methodology block's size
     (in tokens) for the methodology cache to have been read back.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.cache_conversation_helpers import (
    require_api_key, run_turn_via_dispatch, wait_mcp_ready,
)
from tests.methodology_cache_e2e_helpers import (
    assert_block_byte_identical, capture, dump_turn, find_methodology_block,
)
from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from bouzecode.backend.context_manager.methodology import (
    append_ask_user_question_to_methodology,
    append_plan_to_methodology,
    append_user_msg_to_methodology,
    methodology_tool,
)

_MODEL = "claude-sonnet-4-6"
# Lower bound on the cache_read jump between turns that would prove the
# methodology slot was read (not just stable_prefix + tool_docs).
_MIN_CACHE_READ_JUMP_TOKENS = 200


def _fill_methodology_all_paths(gc: ContextState, label: str) -> None:
    """Populate methodology via every auto-append + tool path, with ~2KB of
    filler so the cache_read jump is observable on turn 2."""
    append_user_msg_to_methodology(gc, f"[{label}] q1: lis foo.py et résume")
    methodology_tool(
        {"mode": "append", "content": (
            f"## Notes internes ({label})\nPadding pour dépasser ~2000 chars:\n"
            + ("lorem ipsum dolor sit amet consectetur adipiscing elit. " * 40)
        )},
        {"_context_state": gc},
    )
    append_plan_to_methodology(gc, "1. Lire foo.py\n2. Extraire constantes\n3. Résumer")
    append_ask_user_question_to_methodology(gc, "Quelle version Python ?", "3.11")
    append_user_msg_to_methodology(gc, f"[{label}] q2: continue")


def _assert_cache_read_jumped(turn1, turn2) -> None:
    assert turn2.cache_read_tokens > turn1.cache_read_tokens + _MIN_CACHE_READ_JUMP_TOKENS, (
        "Turn 2 cache_read did NOT meaningfully grow past turn 1 — "
        "the methodology cache-write was not read back.\n"
        f"  turn1: read={turn1.cache_read_tokens:,} create={turn1.cache_creation_tokens:,}\n"
        f"  turn2: read={turn2.cache_read_tokens:,} create={turn2.cache_creation_tokens:,}\n"
    )


def test_methodology_cache_is_read_on_subsequent_turn(capture):
    """Pre-fill methodology via every path, run two real turns, and require:
    stable_prefix + tool_docs + methodology blocks all byte-identical across
    turns, AND turn 2 cache_read > turn 1 cache_read by at least the
    methodology's size."""
    require_api_key()
    wait_mcp_ready()

    gc = ContextState()
    _fill_methodology_all_paths(gc, "setup")
    meth_size = len(gc.notes[METHODOLOGY_NOTE])
    print(f"\n[setup] methodology size = {meth_size:,} chars")
    assert meth_size > 1500, f"need >1500 chars to observe cache effects (got {meth_size})"

    config = {"model": _MODEL, "max_tokens": 32, "_context_state": gc}
    nonce = uuid.uuid4().hex[:8]
    messages = [{"role": "user", "content": f"Salut, dis juste 'ok' (nonce={nonce})"}]

    turn1 = run_turn_via_dispatch(_MODEL, messages, config)
    dump_turn("TURN 1 (cache-write)", turn1, capture.calls[-1])

    messages.append({"role": "assistant", "content": turn1.text or "."})
    next_user = "Encore une réponse courte stp"
    messages.append({"role": "user", "content": next_user})
    append_user_msg_to_methodology(gc, next_user)

    turn2 = run_turn_via_dispatch(_MODEL, messages, config)
    dump_turn("TURN 2 (cache-read)", turn2, capture.calls[-1])

    assert len(capture.calls) == 2
    sys1 = capture.calls[0]["system_blocks"]
    sys2 = capture.calls[1]["system_blocks"]
    m1 = find_methodology_block(sys1)
    m2 = find_methodology_block(sys2)
    assert m1 is not None and m2 is not None, "both turns must carry a methodology block"
    print(
        f"\n[blocks] stable_prefix: t1={len(sys1[0]['text']):,}  t2={len(sys2[0]['text']):,}\n"
        f"[blocks] tool_docs:     t1={len(sys1[1]['text']):,}  t2={len(sys2[1]['text']):,}\n"
        f"[blocks] methodology:   t1={len(m1['text']):,}  t2={len(m2['text']):,}"
    )

    assert_block_byte_identical("stable_prefix", sys1[0]["text"], sys2[0]["text"])
    assert_block_byte_identical("tool_docs",     sys1[1]["text"], sys2[1]["text"])
    assert_block_byte_identical("methodology",   m1["text"], m2["text"])
    _assert_cache_read_jumped(turn1, turn2)


def test_methodology_cache_incremental_append_between_turns(capture):
    """Realistic flow: append to methodology between turns (user msg, plan).
    The snapshot captured after turn 1 must remain a prefix of the current
    methodology — otherwise the cached block is invalidated."""
    require_api_key()
    wait_mcp_ready()

    gc = ContextState()
    methodology_tool(
        {"mode": "append", "content": (
            "## Contexte initial\n"
            + ("Padding pour gonfler le bloc methodology.\n" * 60)
        )},
        {"_context_state": gc},
    )

    config = {"model": _MODEL, "max_tokens": 32, "_context_state": gc}
    nonce = uuid.uuid4().hex[:8]
    first_user = f"Salut, réponds 'ok' (nonce={nonce})"
    append_user_msg_to_methodology(gc, first_user)
    messages = [{"role": "user", "content": first_user}]

    turn1 = run_turn_via_dispatch(_MODEL, messages, config)
    dump_turn("TURN 1 (write)", turn1, capture.calls[-1])

    append_plan_to_methodology(gc, "1. foo\n2. bar\n3. baz")
    messages.append({"role": "assistant", "content": turn1.text or "."})
    u2 = "Résume en 1 phrase, stp."
    messages.append({"role": "user", "content": u2})
    append_user_msg_to_methodology(gc, u2)

    turn2 = run_turn_via_dispatch(_MODEL, messages, config)
    dump_turn("TURN 2 (read)", turn2, capture.calls[-1])

    snap = getattr(gc, "_methodology_cache_snapshot", "")
    current = gc.notes[METHODOLOGY_NOTE]
    assert snap, "snapshot should have been advanced by dispatch after turn 1"
    assert current.startswith(snap), (
        "methodology must still start with the post-turn-1 snapshot "
        f"(snap_len={len(snap)}, current_len={len(current)})"
    )

    m1 = find_methodology_block(capture.calls[0]["system_blocks"])
    m2 = find_methodology_block(capture.calls[1]["system_blocks"])
    assert m1 is not None and m2 is not None
    assert_block_byte_identical("methodology", m1["text"], m2["text"])
    _assert_cache_read_jumped(turn1, turn2)


def test_methodology_cache_hits_across_5_turns_with_growth_every_turn(capture):
    """The hard case that broke in the real session: a Methodology(append)
    tool fires every turn, methodology grows each turn. Under the buggy
    snapshot advance, the block bytes drift each turn → cache miss on N-1's
    write from turn N+1 onward. Under the fix, the snapshot stays frozen
    after the first call → methodology block is byte-identical across all
    subsequent turns → cache reads every turn."""
    require_api_key()
    wait_mcp_ready()

    gc = ContextState()
    methodology_tool(
        {"mode": "append", "content": "## Setup\n" + ("baseline " * 300)},
        {"_context_state": gc},
    )
    config = {"model": _MODEL, "max_tokens": 16, "_context_state": gc}
    nonce = uuid.uuid4().hex[:8]
    first = f"Salut, dis 'ok' (n={nonce})"
    append_user_msg_to_methodology(gc, first)
    messages = [{"role": "user", "content": first}]

    turns = []
    for i in range(5):
        # simulate a tool that grows methodology between every LLM call (real
        # sessions do this via Methodology/Snippet/WritePlan/AskUserQuestion).
        methodology_tool(
            {"mode": "append", "content": f"## Obs{i}\n" + ("x " * 80)},
            {"_context_state": gc},
        )
        t = run_turn_via_dispatch(_MODEL, messages, config)
        turns.append(t)
        dump_turn(f"TURN {i+1}", t, capture.calls[-1])
        messages.append({"role": "assistant", "content": t.text or "."})
        next_u = f"iter {i+1}"
        messages.append({"role": "user", "content": next_u})
        append_user_msg_to_methodology(gc, next_u)

    # The methodology block grows each turn (absorbing the previous delta);
    # each turn's meth block must start with the previous turn's (prefix match).
    meths = [find_methodology_block(c["system_blocks"])["text"] for c in capture.calls]
    print(f"\n[meths] sizes: {[len(m) for m in meths]}")
    for i in range(1, len(meths)):
        assert meths[i].startswith(meths[i-1]), (
            f"Turn {i+1} methodology must start with turn {i} methodology "
            f"(prefix match) — otherwise the cache is invalidated. "
            f"sizes: t{i}={len(meths[i-1])}, t{i+1}={len(meths[i])}"
        )

    # cache_read must grow across turns 2..5 (each turn absorbs prev delta).
    reads = [t.cache_read_tokens for t in turns]
    creates = [t.cache_creation_tokens for t in turns]
    print(f"[reads]   {reads}")
    print(f"[creates] {creates}")
    for i in range(2, 5):
        assert reads[i] >= reads[i-1], (
            f"Turn {i+1} cache_read={reads[i]} should be >= turn {i} cache_read={reads[i-1]} "
            f"— the delta from turn {i} was supposed to be absorbed into cache."
        )
    # And create must stay small (~delta size, not full methodology).
    for i in range(1, 5):
        assert creates[i] < 500, (
            f"Turn {i+1} cache_create={creates[i]} too large — suggests the whole "
            f"methodology was re-cached instead of just the delta."
        )
