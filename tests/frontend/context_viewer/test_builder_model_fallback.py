"""Bug-first repro: model fallback to web-agent sidecar.

BUG: sessions already saved with model="" stay unpriced ($0) forever, even
though the web-agent metadata sidecar (<agent_id>.json) knows the model.

FIX: when the session JSON model is empty, extract_per_call_data resolves it
from the sibling <agent_id>.json sidecar (session file is named
<agent_id>.session.json). CLI sessions (no sidecar) keep "".
"""
import json

from bouzecode.web_v2.runtime.context_viewer import builder
from bouzecode.web_v2.runtime.context_viewer.builder import extract_per_call_data


def test_model_resolved_from_agent_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "_load_turn_dumps", lambda sid: {})

    agent_id = "abc123def456"
    # Sidecar metadata file holds the real model.
    sidecar = tmp_path / f"{agent_id}.json"
    sidecar.write_text(json.dumps({"agent_id": agent_id, "model": "claude-opus-4-8"}), encoding="utf-8")

    # Session JSON written with empty model.
    session = {
        "session_id": "sid-x",
        "model": "",
        "messages": [{"role": "user", "content": "hi"}],
        "compaction_log": [
            {"event": "llm_call", "turn": 1, "timestamp": 100.0,
             "api_input_tokens": 10, "api_output_tokens": 5,
             "api_cache_read": 0, "api_cache_create": 0},
        ],
    }
    session_path = tmp_path / f"{agent_id}.session.json"
    session_path.write_text(json.dumps(session), encoding="utf-8")

    result = extract_per_call_data(str(session_path))
    assert result is not None
    assert result["model"] == "claude-opus-4-8"


def test_cli_session_without_sidecar_keeps_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "_load_turn_dumps", lambda sid: {})

    session = {
        "session_id": "sid-cli",
        "model": "",
        "messages": [{"role": "user", "content": "hi"}],
        "compaction_log": [
            {"event": "llm_call", "turn": 1, "timestamp": 100.0,
             "api_input_tokens": 10, "api_output_tokens": 5,
             "api_cache_read": 0, "api_cache_create": 0},
        ],
    }
    session_path = tmp_path / "plain.session.json"
    session_path.write_text(json.dumps(session), encoding="utf-8")

    result = extract_per_call_data(str(session_path))
    assert result is not None
    # No sidecar -> model unresolved -> preserves pre-existing "?" sentinel.
    assert result["model"] == "?"
