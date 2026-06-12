# [desc] Tests for session_analysis module: turn payload segmentation, cache token accounting, and payload dump loading. [/desc]
"""Tests for session_analysis module — turn payload segmentation."""
import json
from pathlib import Path
from unittest.mock import patch

from bouzecode.backend.agent.session_analysis import (
    analyze_turn_segments,
    analyze_session_turn,
    load_payload_dump,
)


def _make_turn_record(turn=1, cache_read=1000, cache_create=50, in_tokens=200, out_tokens=500):
    return {
        "turn": turn,
        "timestamp": 1700000000.0 + turn,
        "messages": [
            {"role": "user", "content": "Fix the bug in main.py"},
            {"role": "user", "content": "<tool_result>Done</tool_result>"},
        ],
        "system_blocks": [
            {"type": "text", "text": "You are a helpful assistant.", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "## Tools\n- Read\n- Write", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "[METHODOLOGY]\nPlan: fix bug", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "New delta content", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Volatile per-turn info"},
        ],
        "token_counts": {
            "in_tokens": in_tokens,
            "out_tokens": out_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_create,
        },
        "context_state": {"notes": {}},
    }


def test_analyze_turn_segments_cache_read_and_write():
    """Typical turn: prefix cached, new delta written."""
    record = _make_turn_record(cache_read=1000, cache_create=50)
    result = analyze_turn_segments(record)

    # 4 blocks have cache_control
    assert len(result["cached_blocks"]) == 4
    assert "You are a helpful assistant." in result["cached_blocks"][0]
    assert "## Tools" in result["cached_blocks"][1]
    assert "[METHODOLOGY]" in result["cached_blocks"][2]
    assert "New delta content" in result["cached_blocks"][3]

    # 1 volatile block without cache_control
    assert len(result["fresh_blocks"]) == 1
    assert "Volatile per-turn info" in result["fresh_blocks"][0]

    # 2 messages
    assert len(result["messages"]) == 2
    assert "Fix the bug" in result["messages"][0]

    # Token counts preserved
    assert result["token_counts"]["cache_read_tokens"] == 1000
    assert result["token_counts"]["cache_creation_tokens"] == 50


def test_analyze_turn_segments_full_cache_hit():
    """All breakpoints hit, no cache write."""
    record = _make_turn_record(cache_read=2000, cache_create=0)
    result = analyze_turn_segments(record)

    assert len(result["cached_blocks"]) == 4
    assert result["token_counts"]["cache_read_tokens"] == 2000
    assert result["token_counts"]["cache_creation_tokens"] == 0


def test_analyze_turn_segments_no_cache():
    """No cache at all (first turn or non-Anthropic)."""
    record = _make_turn_record(cache_read=0, cache_create=0, in_tokens=3000)
    result = analyze_turn_segments(record)

    assert len(result["cached_blocks"]) == 4
    assert result["token_counts"]["cache_read_tokens"] == 0
    assert result["token_counts"]["in_tokens"] == 3000


def test_analyze_turn_segments_cache_miss_all_write():
    """Cache miss — everything is written to cache."""
    record = _make_turn_record(cache_read=0, cache_create=2000)
    result = analyze_turn_segments(record)

    assert len(result["cached_blocks"]) == 4
    assert result["token_counts"]["cache_creation_tokens"] == 2000


def test_analyze_turn_segments_no_system_blocks():
    """Turn record without system_blocks (e.g. old format dump)."""
    record = {
        "turn": 1,
        "messages": [{"role": "user", "content": "Hello"}],
        "token_counts": {"in_tokens": 100, "out_tokens": 50,
                         "cache_read_tokens": 0, "cache_creation_tokens": 0},
    }
    result = analyze_turn_segments(record)
    assert result["cached_blocks"] == []
    assert result["fresh_blocks"] == []
    assert len(result["messages"]) == 1


def test_load_payload_dump(tmp_path):
    """Load turns from JSONL file."""
    session_id = "test123"
    dump_dir = tmp_path / "debug_payloads" / session_id
    dump_dir.mkdir(parents=True)

    records = [_make_turn_record(i) for i in range(3)]
    with (dump_dir / "turns.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    with patch("bouzecode.backend.agent.session_analysis.CONFIG_DIR", tmp_path):
        loaded = load_payload_dump(session_id)

    assert len(loaded) == 3
    assert loaded[0]["turn"] == 0
    assert loaded[2]["turn"] == 2


def test_analyze_session_turn(tmp_path):
    """Test analysis from saved session's payload dump."""
    session_id = "sess_abc"
    dump_dir = tmp_path / "debug_payloads" / session_id
    dump_dir.mkdir(parents=True)

    records = [_make_turn_record(i) for i in range(2)]
    with (dump_dir / "turns.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    with patch("bouzecode.backend.agent.session_analysis.CONFIG_DIR", tmp_path):
        result = analyze_session_turn(session_id, 1)

    assert len(result["cached_blocks"]) == 4
    assert len(result["messages"]) == 2
    assert result["token_counts"]["out_tokens"] == 500


def test_analyze_turn_index_out_of_range(tmp_path):
    """Verify IndexError on invalid turn index."""
    session_id = "sess_range"
    dump_dir = tmp_path / "debug_payloads" / session_id
    dump_dir.mkdir(parents=True)

    records = [_make_turn_record(0)]
    with (dump_dir / "turns.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    with patch("bouzecode.backend.agent.session_analysis.CONFIG_DIR", tmp_path):
        try:
            analyze_session_turn(session_id, 5)
            assert False, "Should have raised IndexError"
        except IndexError as e:
            assert "out of range" in str(e)
