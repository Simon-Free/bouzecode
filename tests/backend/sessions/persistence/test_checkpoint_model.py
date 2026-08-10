"""Bug-first repro: _save_session_checkpoint must persist the model.

BUG: _save_session_checkpoint called _build_session_data WITHOUT model,
so the written JSON had "model": "" -> web_v2 cost = $0 everywhere.
"""
import json
from types import SimpleNamespace

from bouzecode.backend.commands.session.session import _save_session_checkpoint
from bouzecode.backend.context_manager import ContextState


def _make_state():
    return SimpleNamespace(
        messages=[],
        turn_count=1,
        user_loop_count=0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_cache_read_tokens=0,
        total_cache_creation_tokens=0,
        compaction_log=[],
        distinct_base=0,
        context_state=ContextState(notes={}),
        notes_timeline=[],
        last_api_payload=[],
    )


def test_checkpoint_persists_model(tmp_path):
    state = _make_state()
    session_file = tmp_path / "sess.json"

    _save_session_checkpoint(
        state, str(session_file),
        session_id="sid-1", session_path=str(session_file),
        model="claude-opus-4-8",
    )

    data = json.loads(session_file.read_text(encoding="utf-8"))
    assert data["model"] == "claude-opus-4-8"
