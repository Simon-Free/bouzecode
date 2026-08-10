# [desc] Compaction of the methodology note: free structural pass + paid deep pass. [/desc]
"""Compaction of the methodology note.

Two passes with very different economics.

**Structural pass** (free, no LLM): drops duplicate snippet blocks, snippets of
files that vanished, and stale-marked snippets. Measured on 2 476 real sessions
it frees almost nothing — median yield 0.000, mean 0.001 once the "file is gone
from *this* machine" artefact is removed, and 60 of the 100 notes that crossed
the threshold yielded exactly zero. Kept because it costs nothing, not because
it works.

**Deep pass** (paid): a side-call judges each snippet against the mission and
drops the spent ones, leaving a tombstone. Removing anything rewrites the cached
prefix and forces a full ``cache_create``, so this must be RARE and therefore
DEEP — frequency is the enemy, depth is nearly free once the re-cache is paid.
It is triggered on the size of the CACHED PREFIX (what the re-cache would
actually cost), not on the note alone.
"""

from __future__ import annotations

import os
from pathlib import Path

from .note_blocks import (  # noqa: F401  (re-exported: imported by name elsewhere)
    _extract_snippet_key, _extract_stale_key, _split_into_blocks, path_of_key,
)

COMPACT_TOKENS_THRESHOLD = int(os.environ.get("BOUZECODE_NOTE_COMPACT_TOKENS", "20000"))

# Deep pass: fires on the cached prefix, which is what a compaction re-creates.
# Measured cached tokens per API call: p50 17k, p90 33k, p95 41k, p99 60k — so
# 50k fires in the top ~2-3 % of sessions, which is the intent.
CACHED_TOKENS_THRESHOLD = int(os.environ.get("BOUZECODE_COMPACT_CACHED_TOKENS", "50000"))

# ...but only if the note is a big enough share of it to be worth the call.
DEEP_NOTE_FLOOR_TOKENS = int(os.environ.get("BOUZECODE_COMPACT_NOTE_FLOOR", "10000"))

# A compaction only repays its own cache_create after T = 12.5*(1-f)/f turns —
# 91 turns at the measured MEAN yield ceiling (f=0.121), 20 at its p90 (0.391).
# Firing again before then means the first one never broke even, so the passes
# are spaced by roughly one break-even. Sessions that reach the cached-size
# trigger run p50 75 / p90 185 turns, so the spacing leaves room for 2-6 passes.
MIN_TURNS_BETWEEN_DEEP = int(os.environ.get("BOUZECODE_COMPACT_MIN_TURNS", "30"))


def _source_is_gone(path_str: str) -> bool:
    """True only for a FILE snippet whose source file has disappeared.

    A snippet keyed by ``tool_id`` (an inline tool_result: a loaded doc, a schema)
    names a call id such as ``c3``, not a path — there is no file to look for, and
    treating it as a missing one deleted every documentation snippet the moment the
    note crossed the compaction threshold. Only absolute paths, which is what
    ``resolve_file_lines`` always produces, are checked against the disk.
    """
    candidate = path_str.strip()
    try:
        path = Path(candidate)
        return path.is_absolute() and not path.exists()
    except (OSError, ValueError):
        return False


def compact_methodology(text: str) -> tuple[str, int]:
    """Structural compaction. Returns (compacted_text, chars_removed).

    No tombstone is left for what this pass drops, and that is deliberate: a
    duplicate is superseded by the copy that is kept, and an orphan or a stale
    snippet points at content that no longer exists to be fetched back. A
    tombstone would only be a pointer to nothing.
    """
    if not text:
        return text, 0

    blocks = _split_into_blocks(text)

    stale_keys = {
        key[len("stale:"):] for _, key in blocks
        if key is not None and key.startswith("stale:")
    }
    last_index = {
        key: i for i, (_, key) in enumerate(blocks)
        if key is not None and not key.startswith("stale:")
    }

    kept: list[str] = []
    for i, (block_text, key) in enumerate(blocks):
        if key is None:
            kept.append(block_text)
            continue
        if key.startswith("stale:") or key in stale_keys:
            continue
        if last_index.get(key) != i:
            continue
        if _source_is_gone(path_of_key(key)):
            continue
        kept.append(block_text)

    result = "\n".join(kept).strip()
    return result, len(text) - len(result)


def cached_prefix_tokens(config: dict | None) -> int:
    """Tokens the provider held in cache for the most recent LLM turn.

    ``cache_read + cache_creation`` of the last ``llm`` timing entry is the whole
    cached prefix — stable prompt, tool docs and the methodology block — which is
    exactly what a compaction forces the provider to write again. Returns 0 when
    no LLM turn has completed yet (first turn, side-calls, tests).
    """
    state = (config or {}).get("_state")
    for entry in reversed(getattr(state, "timing_entries", []) or []):
        if entry.get("phase") == "llm":
            return entry.get("cache_read_tokens", 0) + entry.get("cache_creation_tokens", 0)
    return 0


def _deep_compact(context_state, note_key: str, config: dict) -> int:
    """Run the judged pass if the cached prefix has grown expensive enough."""
    if CACHED_TOKENS_THRESHOLD <= 0 or config.get("_depth", 0) > 0:
        return 0
    text = context_state.notes.get(note_key, "")
    if len(text) // 4 < DEEP_NOTE_FLOOR_TOKENS:
        return 0
    if cached_prefix_tokens(config) < CACHED_TOKENS_THRESHOLD:
        return 0
    turn = getattr(config.get("_state"), "turn_count", 0)
    last = getattr(context_state, "_last_deep_compaction_turn", None)
    if last is not None and turn - last < MIN_TURNS_BETWEEN_DEEP:
        return 0
    # Stamped on every ATTEMPT, not every removal: a pass that finds nothing to
    # drop still cost a side-call, and re-paying it each turn is the loss this
    # spacing exists to prevent.
    context_state._last_deep_compaction_turn = turn
    from .compact_judge import judge_and_prune
    pruned, removed = judge_and_prune(text, context_state, config)
    if removed > 0:
        context_state.notes[note_key] = pruned
    return removed


def maybe_compact(context_state, note_key: str = "methodology", config: dict | None = None) -> int:
    """Compact the note; returns chars removed (0 when nothing was done).

    Any removal makes the current note stop being a prefix of the cached
    snapshot, so the snapshot is dropped and the next render pays one full
    ``cache_create``. That is the whole reason compaction must be rare.
    """
    removed = 0
    text = context_state.notes.get(note_key, "")

    if COMPACT_TOKENS_THRESHOLD and len(text) // 4 > COMPACT_TOKENS_THRESHOLD:
        compacted, chars_removed = compact_methodology(text)
        if chars_removed > 0:
            context_state.notes[note_key] = compacted
            removed += chars_removed

    if config is not None:
        removed += _deep_compact(context_state, note_key, config)

    if removed > 0 and hasattr(context_state, "_methodology_cache_snapshot"):
        context_state._methodology_cache_snapshot = None
    return removed
