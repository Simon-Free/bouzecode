# [desc] Reproduces the symbol-snippet cache bug: editing a symbol-snippeted file must NOT mutate the cached methodology block (append a stale marker instead). [/desc]
"""Symbol-snippet cache stability across an edit.

Real reproduction of the prod cache collapse (session 86914e59): the model
snippets a symbol, then edits that file repeatedly. Each render used to
re-resolve the symbol body IN PLACE, mutating the already-cached methodology
block -> the Anthropic prompt cache prefix broke every turn (cache_create
exploded, cache_read frozen at the static prefix).

The contract (append-only cache): editing a symbol-snippeted file must leave
the cached methodology block BYTE-IDENTICAL and only APPEND a stale marker,
exactly like range-based snippets already do.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from bouzecode.backend.context_manager.methodology import (
    snippet_tool,
    methodology_tool,
    build_methodology_system_blocks,
)
from bouzecode.backend.context_manager.stale_hooks import _mark_stale_snippets

_CC = {"type": "ephemeral"}


def _render_and_advance(gc: ContextState):
    """One dispatch render cycle: build the methodology blocks the way
    dispatch.stream() does, then advance the cache snapshot to the raw note."""
    meth = gc.notes.get(METHODOLOGY_NOTE, "") or ""
    snapshot = getattr(gc, "_methodology_cache_snapshot", "") or ""
    blocks, delta = build_methodology_system_blocks(meth, snapshot, _CC)
    if meth:
        gc._methodology_cache_snapshot = meth
    cached = blocks[0]["text"] if blocks else ""
    return cached, delta


def test_editing_symbol_snippeted_file_keeps_cache_prefix_stable(tmp_path):
    """snippet(symbol) -> render -> edit file -> render again.

    The cached methodology block of the second render MUST start with (extend)
    the first one. The refreshed body must NOT overwrite the cached bytes; the
    'now stale' notice must be APPENDED instead.
    """
    f = tmp_path / "test_sym_cache.py"
    f.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    gc = ContextState()

    # --- snippet a symbol (reads the file, freezes its body into methodology) ---
    snippet_tool({"file_path": str(f), "symbol": "greet", "label": "greeter"}, {"_context_state": gc})
    # Real sessions keep working: more notes accumulate AFTER the snippet, so the
    # snippet block sits mid-note (exactly where in-place refresh corrupts the cache).
    methodology_tool({"content": "## Progress\n- [ ] wire greet into the app"}, {"_context_state": gc})

    # --- render turn A: the snapshot now holds the snippet with body "hi" ---
    cached_a, _delta_a = _render_and_advance(gc)
    assert "return 'hi'" in cached_a

    # --- edit the snippeted file: greet body changes ---
    f.write_text("def greet():\n    return 'BONJOUR'\n", encoding="utf-8")
    _mark_stale_snippets(gc, str(f))  # what the Edit/Write hook runs

    # --- render turn B ---
    cached_b, delta_b = _render_and_advance(gc)

    # CACHE PREFIX MUST HOLD: the cached block is never rewritten in place.
    assert cached_b.startswith(cached_a), (
        "CACHE INVALIDATED: the methodology cached block was mutated after "
        "editing a symbol-snippeted file (prefix drifted) -> prompt cache breaks "
        "every turn.\n"
        f"  cached_a (len {len(cached_a)}) tail: {cached_a[-80:]!r}\n"
        f"  cached_b (len {len(cached_b)}) tail: {cached_b[:len(cached_a)][-80:]!r}"
    )
    # The originally-cached body must still be present (never overwritten).
    assert "return 'hi'" in cached_b

    # The 'now stale' warning must be APPENDED (cache-safe), referencing the symbol.
    appended = cached_b[len(cached_a):] + delta_b
    assert "snippet-stale" in appended and "greet" in appended, (
        "expected an appended stale marker for the symbol snippet, got: "
        f"{appended[:200]!r}"
    )
