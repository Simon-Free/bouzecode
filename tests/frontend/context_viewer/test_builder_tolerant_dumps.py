"""Bug-first repro for web_v2 analysis: missing turns.

BUG: extract_per_call_data skipped (continue) any compaction_log turn that
had no matching dump in turns.jsonl. After a --resume, early turns lacked
dumps -> they vanished from the "Tours (analyse)" table.

FIX: emit a minimal row from the compaction_log entry even when the dump is
absent (items=[], tokens_by_status={}), instead of skipping.
"""
import json

from bouzecode.web_v2.runtime.context_viewer import builder
from bouzecode.web_v2.runtime.context_viewer.builder import extract_per_call_data


def _write_turns_jsonl(monkeypatch, session_id, records):
    """Make _load_turn_dumps(session_id) return the given {turn: dump} map."""
    monkeypatch.setattr(builder, "_load_turn_dumps", lambda sid: dict(records))


def test_turn_without_dump_still_emitted(tmp_path, monkeypatch):
    session_id = "sid-tol"
    # A dump only for turn 2; turn 1 has NO dump.
    dumps = {
        2: {
            "messages": [{"role": "user", "content": "hi turn2"}],
            "context_state": {},
        }
    }
    _write_turns_jsonl(monkeypatch, session_id, dumps)

    session = {
        "session_id": session_id,
        "model": "claude-opus-4-8",
        "messages": [{"role": "user", "content": "hi"}],
        "compaction_log": [
            {"event": "llm_call", "turn": 1, "timestamp": 100.0,
             "api_input_tokens": 10, "api_output_tokens": 5,
             "api_cache_read": 0, "api_cache_create": 0},
            {"event": "llm_call", "turn": 2, "timestamp": 200.0,
             "api_input_tokens": 20, "api_output_tokens": 8,
             "api_cache_read": 0, "api_cache_create": 0},
        ],
    }
    session_path = tmp_path / "sess.json"
    session_path.write_text(json.dumps(session), encoding="utf-8")

    result = extract_per_call_data(str(session_path))
    assert result is not None
    turns = [c["turn"] for c in result["calls"]]
    # Turn 1 (no dump) must NOT be dropped.
    assert turns == [1, 2], f"expected both turns, got {turns}"

    call1 = next(c for c in result["calls"] if c["turn"] == 1)
    assert call1["items"] == []
    assert call1["api_input_tokens"] == 10
