"""Bug-first repro: recover ALL turns from turns.jsonl dumps when compaction_log
is truncated (the --resume-from case).

BUG: extract_per_call_data iterated `for entry in log:` over a truncated
compaction_log, so turns present only in the turns.jsonl dump (token_counts)
were invisible in the web_v2 analysis view, and their cost was lost.

FIX: iterate over UNION(log turns, dump turns). For turns missing from the log,
fall back to dump["token_counts"] mapped to api_* fields. Release the early
`return None` when log is empty but dumps exist. _context_state_from_dump must
also accept the legacy `gc_state` key.
"""
import json

from bouzecode.web_v2.runtime.context_viewer import builder
from bouzecode.web_v2.runtime.context_viewer.builder import (
    extract_per_call_data,
    _context_state_from_dump,
)


def _patch_dumps(monkeypatch, records):
    monkeypatch.setattr(builder, "_load_turn_dumps", lambda sid: dict(records))


def _dump(turn, text, token_counts, state_key="context_state"):
    rec = {
        "turn": turn,
        "messages": [{"role": "user", "content": text}],
        "timestamp": float(turn) * 100.0,
        "token_counts": token_counts,
    }
    rec[state_key] = {}
    return rec


def _session(session_id, log):
    return {
        "session_id": session_id,
        "model": "claude-opus-4-8",
        "messages": [{"role": "user", "content": "first"}],
        "compaction_log": log,
    }


def test_truncated_log_recovers_all_turns_from_dumps(tmp_path, monkeypatch):
    session_id = "sid-trunc"
    # Dumps cover turns 1-4. Log is TRUNCATED to turns 3-4 only.
    dumps = {
        1: _dump(1, "t1", {"in_tokens": 100, "out_tokens": 10,
                           "cache_read_tokens": 5, "cache_creation_tokens": 2}),
        2: _dump(2, "t2", {"in_tokens": 200, "out_tokens": 20,
                           "cache_read_tokens": 6, "cache_creation_tokens": 3}),
        3: _dump(3, "t3", {"in_tokens": 300, "out_tokens": 30,
                           "cache_read_tokens": 7, "cache_creation_tokens": 4}),
        4: _dump(4, "t4", {"in_tokens": 400, "out_tokens": 40,
                           "cache_read_tokens": 8, "cache_creation_tokens": 5}),
    }
    _patch_dumps(monkeypatch, dumps)

    log = [
        {"event": "llm_call", "turn": 3, "timestamp": 333.0,
         "api_input_tokens": 999, "api_output_tokens": 99,
         "api_cache_read": 9, "api_cache_create": 1},
        {"event": "llm_call", "turn": 4, "timestamp": 444.0,
         "api_input_tokens": 888, "api_output_tokens": 88,
         "api_cache_read": 8, "api_cache_create": 0},
    ]
    session_path = tmp_path / "sess.json"
    session_path.write_text(json.dumps(_session(session_id, log)), encoding="utf-8")

    result = extract_per_call_data(str(session_path))
    assert result is not None
    turns = [c["turn"] for c in result["calls"]]
    # AFTER fix: all 4 turns present (BEFORE fix: only [3, 4]).
    assert turns == [1, 2, 3, 4], f"expected 1..4, got {turns}"

    by_turn = {c["turn"]: c for c in result["calls"]}
    # Turn 1-2 absent from log -> api_* reconstructed from dump token_counts.
    assert by_turn[1]["api_input_tokens"] == 100
    assert by_turn[1]["api_output_tokens"] == 10
    assert by_turn[1]["api_cache_read"] == 5
    assert by_turn[1]["api_cache_create"] == 2
    assert by_turn[2]["api_input_tokens"] == 200
    # Reconstructed turns build real items from the dump payload.
    assert by_turn[1]["items"] != []

    # Non-regression: turns in BOTH log and dump -> LOG values are authoritative.
    assert by_turn[3]["api_input_tokens"] == 999
    assert by_turn[4]["api_input_tokens"] == 888


def test_empty_log_with_dumps_still_returns(tmp_path, monkeypatch):
    session_id = "sid-empty-log"
    dumps = {
        1: _dump(1, "t1", {"in_tokens": 50, "out_tokens": 5,
                           "cache_read_tokens": 0, "cache_creation_tokens": 0}),
    }
    _patch_dumps(monkeypatch, dumps)
    # No llm_call entries at all in compaction_log.
    session_path = tmp_path / "sess.json"
    session_path.write_text(json.dumps(_session(session_id, [])), encoding="utf-8")

    result = extract_per_call_data(str(session_path))
    assert result is not None, "empty log + dumps must not return None"
    assert [c["turn"] for c in result["calls"]] == [1]
    assert result["calls"][0]["api_input_tokens"] == 50


def test_cost_nonzero_for_reconstructed_turn(tmp_path, monkeypatch):
    from bouzecode.web_v2.services.sessions.costs import calc_cost

    cost = calc_cost("claude-opus-4-8", 100, 10, 5, 2)
    assert cost > 0, "reconstructed turn tokens must yield a non-zero cost"


def test_context_state_from_dump_accepts_legacy_gc_state():
    # Old dumps used the `gc_state` key instead of `context_state`.
    ns = _context_state_from_dump({"gc_state": {"notes": {"x": "y"}}})
    assert ns.notes == {"x": "y"}
