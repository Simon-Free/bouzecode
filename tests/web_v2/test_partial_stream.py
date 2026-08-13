"""Tests for token-streaming partials.

Three concerns, all with fixtures DERIVED FROM THE REAL producer:
- Unit backend: write_partial / clear_partial / throttle (pure filesystem, no Flask).
- API contract: GET /api/sessions/<key>/partial reads the real .partial.json format.

The .partial.json content is never hand-invented: it is produced by the real
``partial_stream.write_partial`` and read back, so the test exercises the true
contract shared between runner and web_v2.

The throttle tests DRIVE the clock instead of racing it (see ``clock`` below). The
module's write state is process-wide; it is restored by ``_isolate_global_state`` in
``tests/conftest.py``, not by a fixture local to this file — the agent loop calls
``write_partial`` too, so the leak was never this file's alone.
"""
import json

import pytest

from bouzecode.backend.agent import partial_stream as ps


class _HandCrankedClock:
    """A monotonic clock the test moves itself, one ``advance`` at a time."""

    def __init__(self, start: float = 1_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    """Replace the throttle's clock so elapsed time is stated, never hoped for.

    `write_partial` decides on `_clock() - _last_write_at`. A test that writes twice
    in a row and *expects* to still be inside the 120 ms window measures the machine,
    not the throttle: under load two consecutive statements can straddle the boundary,
    the second write lands, and the test blames a defect that does not exist."""
    fake = _HandCrankedClock()
    monkeypatch.setattr(ps, "_clock", fake)
    return fake


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


def test_write_partial_throttles_rapid_small_writes(tmp_path, clock):
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    partial = session.with_suffix(".partial.json")

    # First write (forced) lands.
    ps.write_partial(config, turn=1, text="ab", force=True)
    seq_after_first = json.loads(partial.read_text(encoding="utf-8"))["seq"]

    # Small growth (< _MIN_CHARS) still inside _MIN_INTERVAL_S -> throttled skip.
    clock.advance(ps._MIN_INTERVAL_S / 2)
    ps.write_partial(config, turn=1, text="abc")
    seq_after_second = json.loads(partial.read_text(encoding="utf-8"))["seq"]
    assert seq_after_second == seq_after_first, "small rapid write should be throttled"


def test_write_partial_resumes_once_the_interval_elapsed(tmp_path, clock):
    """The complement of the test above: the throttle DELAYS a write, it never drops it.

    Without this, widening the window would pass the throttling test — the two
    together pin the boundary from both sides."""
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    partial = session.with_suffix(".partial.json")

    ps.write_partial(config, turn=1, text="ab", force=True)
    seq_after_first = json.loads(partial.read_text(encoding="utf-8"))["seq"]

    clock.advance(ps._MIN_INTERVAL_S)
    ps.write_partial(config, turn=1, text="abc")
    payload = json.loads(partial.read_text(encoding="utf-8"))
    assert payload["seq"] > seq_after_first
    assert payload["text"] == "abc"


def test_write_partial_flushes_when_enough_chars_accumulated(tmp_path, clock):
    session = tmp_path / "session_120000_abcd.json"
    config = {"_session_path": str(session)}
    partial = session.with_suffix(".partial.json")

    ps.write_partial(config, turn=1, text="ab", force=True)
    seq1 = json.loads(partial.read_text(encoding="utf-8"))["seq"]

    # The clock does NOT move: only the char bypass can let this write through, so
    # the test cannot pass by accident on a machine that spent 120 ms getting here.
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


def test_a_write_arms_the_process_wide_throttle(tmp_path):
    """Deliberately leaves the module's globals dirty, as any agent turn does.

    Paired with the test below: `write_partial` is called by the agent loop, so EVERY
    test crossing a turn leaves the throttle armed and the sequence counter advanced for
    the rest of the worker. Nothing here is exotic — that is exactly the leak."""
    session = tmp_path / "session_120000_abcd.json"
    ps.write_partial({"_session_path": str(session)}, turn=1, text="dirty", force=True)

    assert ps._seq == 1 and ps._last_len == 5 and ps._last_write_at != 0.0


def test_the_next_test_starts_from_a_clean_throttle():
    """`_isolate_global_state` (tests/conftest.py) puts the three globals back at rest.

    This used to be the job of a fixture local to this one file, which left every OTHER
    test in the suite exposed. The idle state is POSED at setup, not merely restored at
    teardown, so this holds whichever test — from whichever tree — ran before."""
    assert (ps._last_write_at, ps._last_len, ps._seq) == (0.0, 0, 0)


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
