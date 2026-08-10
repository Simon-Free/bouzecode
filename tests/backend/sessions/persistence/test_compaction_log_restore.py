# [desc] Tests that the compaction log survives a session save/restore cycle across agent respawns. [/desc]
"""The compaction history must survive a respawn — unit level on purpose.

When an agent is respawned, its session JSON is written by one process and read
back by another. The invariant here (compaction entries are carried across, a
legacy session without them restores to an empty log, entries accumulate rather
than reset) spans that save/restore boundary, which a single in-process
bouzecode() conversation never crosses.
"""
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.session.session_pick import restore_state as _restore_state


def _entry(turn: int) -> dict:
    return {
        "turn": turn,
        "api_input_tokens": 100 + turn,
        "api_output_tokens": 10 + turn,
        "api_cache_read": 0,
        "api_cache_create": 0,
        "timestamp": float(turn),
    }


def test_compaction_log_preserved_on_restore():
    state = AgentState()
    state.compaction_log = [_entry(1), _entry(2)]
    data = _build_session_data(state, session_id="s1", model="m")

    restored = AgentState()
    _restore_state(restored, data)

    assert restored.compaction_log == [_entry(1), _entry(2)]


def test_legacy_session_without_compaction_log_defaults_empty():
    # Old sessions saved before the fix have no compaction_log key.
    data = {"messages": [], "turn_count": 0}
    restored = AgentState()
    _restore_state(restored, data)

    assert restored.compaction_log == []


def test_compaction_log_accumulates_across_respawns():
    # Segment 1: subprocess writes entries for turns 1-2, then saves.
    seg1 = AgentState()
    seg1.compaction_log = [_entry(1), _entry(2)]
    data1 = _build_session_data(seg1, session_id="s1", model="m")

    # Segment 2: respawn restores, appends turn 3, re-saves.
    seg2 = AgentState()
    _restore_state(seg2, data1)
    seg2.compaction_log.append(_entry(3))
    data2 = _build_session_data(seg2, session_id="s1", model="m")

    # Final restore must contain ALL turns, not just the last segment.
    final = AgentState()
    _restore_state(final, data2)

    turns = [e["turn"] for e in final.compaction_log]
    assert turns == [1, 2, 3]
