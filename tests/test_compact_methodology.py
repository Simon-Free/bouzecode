"""The note compaction trigger: each pass is armed by the material IT can remove.

Compacting always breaks the cached prefix and makes the next render pay a full
``cache_create``, so the bar stays high. But the size of the cached prefix was
the wrong measure of it: about half of that prefix is the stable prompt and the
tool docs, which no compaction can touch. A pass would fire on 50k cached
tokens and be handed a fifth of that to summarise, with a ceiling computed on
what it was handed — unreachable by construction, 78 % of the passes removing
nothing at all.

So the trigger now measures what each pass can actually delete: compactable
PROSE for the summary pass, LIVE SNIPPETS for the judge. See
tests/backend/compaction/test_compact_trigger.py for the two thresholds and the
routing between them; this module keeps the guards and the snippet-key reading.
"""

from __future__ import annotations

from bouzecode.backend.context_manager.compact_methodology import (
    CHARS_PER_TOKEN,
    NOTE_PROSE_TOKENS_THRESHOLD,
    _extract_snippet_key,
    _split_into_blocks,
    maybe_compact,
    should_compact,
)


# --- The snippet key, as read off a note header ---


def test_extract_key_range_based():
    header = '## snippet: C:\\code\\foo.py L10-25 — "some label"'
    assert _extract_snippet_key(header) == "C:\\code\\foo.py:L10-25"


def test_extract_key_symbol_based():
    header = '## snippet: /home/user/bar.py :: MyClass.method — "label"'
    assert _extract_snippet_key(header) == "/home/user/bar.py::MyClass.method"


def test_extract_key_no_label():
    header = "## snippet: /tmp/x.py :: func"
    assert _extract_snippet_key(header) == "/tmp/x.py::func"


def test_extract_key_not_snippet():
    assert _extract_snippet_key("## Turn 5 - some note") is None
    assert _extract_snippet_key("regular line") is None


# --- Splitting the note into prose blocks and snippet blocks ---


def test_split_simple():
    text = (
        "## Turn 1\nsome notes\n"
        '## snippet: /a.py L1-5 — "x"\n  1  line1\n  2  line2\n'
        "## Turn 2\nmore notes"
    )
    blocks = _split_into_blocks(text)
    assert len(blocks) == 3
    assert blocks[0][1] is None  # non-snippet
    assert blocks[1][1] == "/a.py:L1-5"  # snippet
    assert blocks[2][1] is None  # non-snippet


# --- The gate: how much compactable material the note carries ---


class FakeSession:
    """The session log, reduced to what the compaction writes and reads.

    ``timing_entries`` is no longer what arms the pass — it is journalled next to
    it, so a run can still be compared against what the old trigger would have
    seen."""

    def __init__(self, cached_tokens: int):
        self.turn_count = 0
        self.compaction_log: list = []
        self.timing_entries = [{
            "phase": "llm", "in_tokens": 500,
            "cache_read_tokens": cached_tokens, "cache_creation_tokens": 0,
        }]


class FakeContextState:
    def __init__(self, text: str):
        self.notes = {"methodology": text}
        self._methodology_cache_snapshot = "some snapshot"


def _config(cached_tokens: int = 0, depth: int = 0) -> dict:
    return {"_state": FakeSession(cached_tokens), "_depth": depth}


NOTE = "## Turn 1\nsome reasoning worth keeping\n"

# Enough prose to arm the summary pass. Built FROM the constants, never from a
# literal: a threshold moved tomorrow must move this note with it, otherwise the
# test would keep passing while proving nothing.
_UNIT = "constat mesure a garder. "
BIG_NOTE = "## Turn 1\n" + _UNIT * int(
    NOTE_PROSE_TOKENS_THRESHOLD * CHARS_PER_TOKEN / len(_UNIT) + 100)


def test_a_note_with_little_prose_is_left_alone():
    """A cheap note is not compacted, however expensive the cached prefix got.

    This is the case the old trigger got wrong: 50k cached tokens with nothing
    summarisable in the note used to buy a full side-call and a broken cache."""
    state = FakeContextState(NOTE)
    assert should_compact(state, "methodology", _config(60_000)) is False
    assert maybe_compact(state, "methodology", _config(60_000)) == 0
    assert state.notes["methodology"] == NOTE


def test_a_note_heavy_in_prose_is_compacted():
    """Past the prose threshold the paid passes are allowed to run."""
    state = FakeContextState(BIG_NOTE)
    assert should_compact(state, "methodology", _config()) is True


def test_a_side_call_never_compacts_its_own_context():
    """`_depth` > 0 means we are already inside a side-call: no recursion."""
    state = FakeContextState(BIG_NOTE)
    assert should_compact(state, "methodology", _config(depth=1)) is False


def test_no_config_means_no_trigger():
    """Without the session there is no side-call to run and nothing to journal."""
    state = FakeContextState(BIG_NOTE)
    assert should_compact(state, "methodology", None) is False
    assert maybe_compact(state, "methodology", None) == 0


def test_an_empty_note_is_never_compacted():
    state = FakeContextState("")
    assert should_compact(state, "methodology", _config()) is False
    assert maybe_compact(state, "methodology", _config()) == 0


def test_a_missing_note_key_is_never_compacted():
    state = FakeContextState(BIG_NOTE)
    assert should_compact(state, "other_note", _config()) is False
