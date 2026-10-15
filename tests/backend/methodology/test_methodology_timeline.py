# [desc] <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that notes_timeline stores dated per-turn deltas and reconstructs the methodology block by folding the journal.</param></tool_use> [/desc]
"""Tests that notes_timeline stores per-turn deltas (added/updated/removed) with
metadata, and that the full methodology block can be reconstructed by folding the
journal."""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
