"""RED test (test-first): the context diag must segment by system_blocks +
cache_control, not by message payload_idx.

Truth of the Anthropic prefix cache = the `system_blocks` marked `cache_control`
(stable prefix, tool docs, methodology, delta). The volatile Session Context
block (no cache_control) and the conversation messages are always fresh.

The current diag ignores `record["system_blocks"]` entirely and segments the
messages by position, so this test FAILS on the current code. It will pass once
build_turn_context_diag consumes system_blocks (V1).
"""
import json

import pytest

from bouzecode.web_v2.services.sessions.context_diag import build_turn_context_diag


def _cc():
    return {"type": "ephemeral"}


@pytest.fixture()
def sysblocks_env(tmp_path, monkeypatch):
    """A single-turn session whose dump carries rich system_blocks."""
    from bouzecode.backend.core import config as config_mod
    import bouzecode.backend.core.config as _c

    cfg = tmp_path / "cfg"
    (cfg / "sessions" / "daily").mkdir(parents=True)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", str(cfg))
    monkeypatch.setattr(_c, "CONFIG_DIR", str(cfg))

    sid = "sysblk001"

    # system_blocks = [stable+CC, tools+CC, methodology+CC, delta+CC, volatile(no CC)]
    system_blocks = [
        {"type": "text", "text": "STABLE PREFIX identity/guidelines", "cache_control": _cc()},
        {"type": "text", "text": "TOOL DOCS block", "cache_control": _cc()},
        {"type": "text", "text": "## Methodology note\n- [x] done", "cache_control": _cc()},
        {"type": "text", "text": "DELTA recent methodology", "cache_control": _cc()},
        {"type": "text", "text": "# Session Context\nCurrent date: 2026-07-16"},  # volatile, no CC
    ]
    messages = [
        {"role": "user", "content": "U1 question"},
        {"role": "assistant", "content": "A1 answer"},
    ]

    dumps_dir = cfg / "debug_payloads" / sid
    dumps_dir.mkdir(parents=True)
    record = {
        "turn": 1,
        "timestamp": "2026-07-16T10:00:00",
        "messages": messages,
        "context_state": {"notes": {"main": "## Methodology note\n- [x] done"}},
        "system_blocks": system_blocks,
        "token_counts": {"in_tokens": 50, "out_tokens": 10,
                          "cache_read_tokens": 0, "cache_creation_tokens": 400},
    }
    (dumps_dir / "turns.jsonl").write_text(json.dumps(record), encoding="utf-8")

    session = {
        "session_id": sid,
        "saved_at": "2026-07-16T10:00:00",
        "model": "claude-test",
        "first_message": "U1 question",
        "messages": messages,
        "system_prompt": "STABLE PREFIX identity/guidelines",
        "compaction_log": [
            {"event": "llm_call", "turn": 1, "timestamp": "2026-07-16T10:00:00",
             "api_input_tokens": 50, "api_output_tokens": 10,
             "api_cache_read": 0, "api_cache_create": 400, "est_message_tokens": 60}
        ],
    }
    session_path = cfg / "sessions" / "daily" / f"session_100000_{sid}.json"
    session_path.write_text(json.dumps(session), encoding="utf-8")
    return {"session_path": str(session_path), "sid": sid}


def _texts(items):
    return [i.get("text") or i.get("preview") or "" for i in items]


def test_diag_segments_by_system_blocks(sysblocks_env):
    result = build_turn_context_diag(sysblocks_env["session_path"], 1)
    cached = result["cached_items"]
    cached_text = " || ".join(_texts(cached))

    # The 4 cache_control blocks must appear as CACHED items.
    assert "STABLE PREFIX" in cached_text, cached_text
    assert "TOOL DOCS" in cached_text, cached_text
    assert "Methodology note" in cached_text, cached_text
    assert "DELTA recent" in cached_text, cached_text

    # The volatile Session Context block (no cache_control) must NOT be cached.
    assert "Session Context" not in cached_text, cached_text

    # Conversation messages are never in the cached (prefix) section.
    assert "U1 question" not in cached_text, cached_text
    assert "A1 answer" not in cached_text, cached_text
