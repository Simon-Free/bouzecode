"""Pre-expiration compaction: a tool batch running longer than the cache TTL
compacts the note before the next (anyway uncached) call."""
import threading
import time
from types import SimpleNamespace

from bouzecode.backend.context_manager.compact_methodology import CHARS_PER_TOKEN, NOTE_LOCK
from bouzecode.backend.context_manager.compact_precache import (
    precache_compact,
    should_precache_compact,
    start_precache_watchdog,
)


def _cs(tokens: int, last_compact_turn: int = 0):
    return SimpleNamespace(
        notes={"methodology": "x" * int(tokens * CHARS_PER_TOKEN + 10)},
        allegements=0,
        last_compact_turn=last_compact_turn,
        _methodology_cache_snapshot="snap",
    )


def _config(turn: int, **extra):
    cfg = {"_state": SimpleNamespace(turn_count=turn)}
    cfg.update(extra)
    return cfg


def _halve(text: str) -> str:
    return text[: len(text) // 2]


def test_big_note_old_compaction_triggers():
    assert should_precache_compact(_cs(31000), "methodology", _config(12))


def test_small_note_does_not_trigger():
    assert not should_precache_compact(_cs(29000), "methodology", _config(12))


def test_recent_compaction_does_not_trigger():
    assert not should_precache_compact(_cs(31000, last_compact_turn=5), "methodology", _config(14))
    assert should_precache_compact(_cs(31000, last_compact_turn=5), "methodology", _config(15))


def test_side_call_never_triggers():
    annexe = _config(12, _depth=1, _context_state=None)
    assert not should_precache_compact(_cs(31000), "methodology", annexe)


def test_sub_agent_triggers_on_its_own_note():
    cs = _cs(31000)
    assert should_precache_compact(cs, "methodology", _config(12, _depth=1, _context_state=cs))


def test_precache_compact_rewrites_note_and_records_turn():
    cs = _cs(31000)
    before = len(cs.notes["methodology"])
    removed = precache_compact(cs, "methodology", _config(12), passes=_halve)
    assert removed == before - before // 2
    assert len(cs.notes["methodology"]) == before // 2
    assert cs.last_compact_turn == 12
    assert cs.allegements == 1
    assert cs._methodology_cache_snapshot is None


def test_append_during_compaction_is_kept():
    cs = _cs(31000)

    def slow_passes(text):
        cs.notes["methodology"] = text + "\n\nAPPENDED"
        return "SUMMARY"

    precache_compact(cs, "methodology", _config(12), passes=slow_passes)
    assert cs.notes["methodology"] == "SUMMARY\n\nAPPENDED"


def test_rewritten_note_during_compaction_is_abandoned():
    cs = _cs(31000)

    def rewriting_passes(text):
        cs.notes["methodology"] = "REWRITTEN"
        return "SUMMARY"

    assert precache_compact(cs, "methodology", _config(12), passes=rewriting_passes) == 0
    assert cs.notes["methodology"] == "REWRITTEN"
    assert cs.last_compact_turn == 0


def test_watchdog_fires_after_delay():
    cs = _cs(31000)
    done = threading.Event()

    def passes(text):
        done.set()
        return _halve(text)

    timer = start_precache_watchdog(_config(12, precache_compact_delay_s=0.05), cs, passes=passes)
    assert timer is not None
    assert done.wait(2)
    timer.join(2)
    assert cs.last_compact_turn == 12


def test_watchdog_cancelled_when_tools_finish_early():
    cs = _cs(31000)
    called = []
    timer = start_precache_watchdog(_config(12, precache_compact_delay_s=0.3), cs,
                                    passes=lambda t: called.append(t) or _halve(t))
    timer.cancel()
    time.sleep(0.5)
    assert not called
    assert cs.last_compact_turn == 0


def test_watchdog_disabled_without_session_or_in_side_call():
    assert start_precache_watchdog(None) is None
    assert start_precache_watchdog(_config(12, _depth=1, _context_state=None)) is None
    assert start_precache_watchdog(_config(12, precache_compact_delay_s=0)) is None


def test_lock_is_reentrant():
    with NOTE_LOCK:
        with NOTE_LOCK:
            pass
