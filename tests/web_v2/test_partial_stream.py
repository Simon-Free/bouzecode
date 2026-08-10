"""Tests for token-streaming partials.

Three concerns, all with fixtures DERIVED FROM THE REAL producer:
- Unit backend: write_partial / clear_partial / throttle (pure filesystem, no Flask).
- API contract: GET /api/sessions/<key>/partial reads the real .partial.json format.

The .partial.json content is never hand-invented: it is produced by the real
``partial_stream.write_partial`` and read back, so the test exercises the true
contract shared between runner and web_v2.
"""
import json

import pytest

from bouzecode.backend.agent import partial_stream as ps


@pytest.fixture(autouse=True)
def _reset_partial_globals():
    """partial_stream keeps process-wide write state — reset before each test."""
    ps._last_write_at = 0.0
    ps._last_len = 0
    ps._seq = 0
    yield


# ---------------------------------------------------------------------------
# Unit backend: write_partial / clear_partial / throttle
# ---------------------------------------------------------------------------

def test_write_partial_creates_file_with_expected_json(tmp_path):
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}

    ps.write_partial(config, turn=3, text="Hello", force=True)

    partial = session.with_suffix(".partial.json")
    assert partial.exists()
    data = json.loads(partial.read_text(encoding="utf-8"))
    assert data == {"turn": 3, "seq": 1, "phase": "text", "text": "Hello", "thinking": ""}


def test_write_partial_noop_without_session_path(tmp_path):
    # CLI mode: no _session_path -> silent no-op, nothing written anywhere.
    config = {}
    ps.write_partial(config, turn=0, text="whatever", force=True)
    assert list(tmp_path.iterdir()) == []


def test_write_partial_falls_back_to_session_file(tmp_path):
    # Web agents (subprocess spawned by web/runner via --session-file) only get
    # _session_file in config; _session_path stays unset until the first lazy
    # save_progressive. write_partial must still emit the partial alongside the
    # session file so GET /partial (ref.path.with_suffix('.partial.json')) finds it.
    session = tmp_path / "abcd1234.session.json"
    config = {"_session_file": str(session)}  # no _session_path

    ps.write_partial(config, turn=2, text="live tokens", force=True)

    partial = session.with_suffix(".partial.json")
    assert partial.exists(), "streaming must work for web agents with only _session_file"
    data = json.loads(partial.read_text(encoding="utf-8"))
    assert data == {"turn": 2, "seq": 1, "phase": "text", "text": "live tokens", "thinking": ""}


def test_write_partial_throttles_rapid_small_writes(tmp_path):
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    partial = session.with_suffix(".partial.json")

    # First write (forced) lands.
    ps.write_partial(config, turn=1, text="ab", force=True)
    seq_after_first = json.loads(partial.read_text(encoding="utf-8"))["seq"]

    # Immediate small growth (< _MIN_CHARS) within _MIN_INTERVAL_S -> throttled skip.
    ps.write_partial(config, turn=1, text="abc")
    seq_after_second = json.loads(partial.read_text(encoding="utf-8"))["seq"]
    assert seq_after_second == seq_after_first, "small rapid write should be throttled"


def test_write_partial_flushes_when_enough_chars_accumulated(tmp_path):
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    partial = session.with_suffix(".partial.json")

    ps.write_partial(config, turn=1, text="ab", force=True)
    seq1 = json.loads(partial.read_text(encoding="utf-8"))["seq"]

    # >= _MIN_CHARS new chars bypasses the time throttle even without force.
    big = "ab" + "x" * (ps._MIN_CHARS + 1)
    ps.write_partial(config, turn=1, text=big)
    payload = json.loads(partial.read_text(encoding="utf-8"))
    assert payload["seq"] > seq1
    assert payload["text"] == big


def test_clear_partial_removes_file_and_resets_state(tmp_path):
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    partial = session.with_suffix(".partial.json")

    ps.write_partial(config, turn=1, text="something", force=True)
    assert partial.exists()

    ps.clear_partial(config)
    assert not partial.exists()
    assert ps._last_write_at == 0.0
    assert ps._last_len == 0


def test_clear_partial_silent_when_absent(tmp_path):
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    # No file written yet -> must not raise.
    ps.clear_partial(config)


# ---------------------------------------------------------------------------
# API contract: GET /api/sessions/<key>/partial
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class _Ref:
    def __init__(self, path):
        self.path = path
        self.agent = None


def test_api_partial_returns_written_payload(client, tmp_path, monkeypatch):
    from bouzecode.web_v2.routes import sessions as sessions_routes

    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    # Produce the partial with the REAL writer (true contract, not invented JSON).
    ps.write_partial(config, turn=7, text="streaming text", force=True)

    monkeypatch.setattr(
        sessions_routes, "_resolve_or_404",
        lambda key: (_Ref(session), None),
    )

    resp = client.get("/api/sessions/anykey/partial")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["turn"] == 7
    assert body["text"] == "streaming text"
    assert isinstance(body["seq"], int)


def test_api_partial_returns_null_when_absent(client, tmp_path, monkeypatch):
    from bouzecode.web_v2.routes import sessions as sessions_routes

    session = tmp_path / "session_999999_none.json"  # no .partial.json alongside
    monkeypatch.setattr(
        sessions_routes, "_resolve_or_404",
        lambda key: (_Ref(session), None),
    )

    resp = client.get("/api/sessions/anykey/partial")
    assert resp.status_code == 200
    assert resp.get_json()["text"] is None
