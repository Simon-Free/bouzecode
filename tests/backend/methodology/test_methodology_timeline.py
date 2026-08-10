# [desc] Tests that notes_timeline stores dated per-turn deltas and reconstructs the methodology block across compaction. [/desc]
"""Tests that notes_timeline stores per-turn deltas (added/updated/removed) with
metadata, and that the full methodology block can be reconstructed by folding the
journal — robustly across a compaction event."""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bouzecode.backend.context_manager import compact_methodology
from bouzecode.backend.context_manager.methodology import (
    methodology_tool,
    reconstruct_methodology_from_timeline,
    snippet_tool,
)
from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE


def _state_config():
    state = types.SimpleNamespace(notes_timeline=[], turn_count=0)
    cfg = {"_context_state": ContextState(), "_state": state}
    return state, cfg


def _bump(state, cfg):
    """Simulate the runtime advancing to the next turn."""
    state.turn_count += 1


def test_timeline_records_dated_delta_per_turn():
    state, cfg = _state_config()

    _bump(state, cfg)
    methodology_tool({"content": "## Goal\nfix the bug"}, cfg)
    _bump(state, cfg)
    methodology_tool({"content": "## Findings\nroot cause in foo()"}, cfg)
    _bump(state, cfg)
    methodology_tool({"content": "## Decision\nappend-only journal"}, cfg)

    tl = state.notes_timeline
    assert len(tl) == 3
    # Each entry carries turn metadata, a timestamp and a delta.
    for i, entry in enumerate(tl):
        assert entry["turn"] == i + 1
        assert isinstance(entry["timestamp"], float)
        assert "delta" in entry, "each timeline entry must carry a delta dict"
        d = entry["delta"]
        assert set(d) >= {"added", "updated", "removed"}
    # Turn 1 introduces the Goal block as an addition.
    assert any("fix the bug" in b for b in tl[0]["delta"]["added"])
    # Turn 2 adds a new block, does not touch the first.
    assert any("root cause in foo()" in b for b in tl[1]["delta"]["added"])
    assert tl[1]["delta"]["removed"] == []


def test_reconstruction_matches_current_note():
    state, cfg = _state_config()
    _bump(state, cfg)
    methodology_tool({"content": "## Goal\nship feature"}, cfg)
    _bump(state, cfg)
    snippet_tool(
        {
            "file_path": "/abs/example.py",
            "ranges": [[1, 3]],
            "label": "example",
        },
        cfg,
    )
    _bump(state, cfg)
    methodology_tool({"content": "## Next\nwrite the docs"}, cfg)

    rebuilt = reconstruct_methodology_from_timeline(state.notes_timeline)
    assert rebuilt == cfg["_context_state"].notes[METHODOLOGY_NOTE]


def test_reconstruction_robust_to_compaction(monkeypatch, tmp_path):
    # Force compaction to trigger on the next append by lowering the threshold.
    state, cfg = _state_config()
    # A REAL source file so snippet_tool produces valid '## snippet:' blocks
    # (compaction only dedups blocks with a recognised snippet key; a
    # '## snippet ERROR:' from a missing path has key=None and is never purged).
    src = tmp_path / "a.py"
    src.write_text("line1\nline2\nline3\n", encoding="utf-8")
    _bump(state, cfg)
    # Seed two IDENTICAL snippet blocks (compaction dedups → keeps the last).
    snippet_tool(
        {"file_path": str(src), "ranges": [[1, 2]], "label": "a"}, cfg
    )
    _bump(state, cfg)
    snippet_tool(
        {"file_path": str(src), "ranges": [[1, 2]], "label": "a"}, cfg
    )
    _bump(state, cfg)
    # Now shrink the compaction threshold so the next append compacts.
    monkeypatch.setattr(compact_methodology, "COMPACT_TOKENS_THRESHOLD", 1)
    methodology_tool({"content": "## Trigger\nforce compaction now"}, cfg)

    # At least one timeline entry must record a removal (the compaction event).
    assert any(
        entry["delta"]["removed"] for entry in state.notes_timeline
    ), "compaction must be journalled as a removed delta"

    # Reconstruction still reproduces the final (post-compaction) note exactly.
    rebuilt = reconstruct_methodology_from_timeline(state.notes_timeline)
    assert rebuilt == cfg["_context_state"].notes[METHODOLOGY_NOTE]
