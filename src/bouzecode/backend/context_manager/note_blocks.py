# [desc] Parse the methodology note into snippet blocks and stale markers. [/desc]
"""Block-level parsing of the methodology note.

One place decides what a snippet block *is*, so compaction, the judge and the
tests all agree on the same boundaries and the same dedup key.
"""
from __future__ import annotations

import re

# A snippet header line, range-based (L<start>-<end>) or symbol-based (:: <symbol>).
_SNIPPET_HEADER_RE = re.compile(
    r"^## snippet: (?P<path>.+?)"
    r"(?: L(?P<start>\d+)-(?P<end>\d+)| :: (?P<symbol>[^\s—]+))"
    r"(?: — .*)?\s*$"
)

# A stale marker, appended after an Edit/Write touched a snippeted file.
_STALE_MARKER_RE = re.compile(
    r"^## snippet-stale: (?P<path>.+?)"
    r"(?: L(?P<start>\d+)-(?P<end>\d+)| :: (?P<symbol>[^\s—]+))"
    r"(?: — .*)?\s*$"
)


def _key_from_match(m: "re.Match | None") -> str | None:
    if not m:
        return None
    path = m.group("path").strip()
    if m.group("symbol"):
        return f"{path}::{m.group('symbol')}"
    return f"{path}:L{m.group('start')}-{m.group('end')}"


def _extract_stale_key(header: str) -> str | None:
    """Return the snippet key a stale marker refers to, or None."""
    return _key_from_match(_STALE_MARKER_RE.match(header.strip()))


def _extract_snippet_key(header: str) -> str | None:
    """Return a dedup key from a snippet header, or None if not a snippet."""
    return _key_from_match(_SNIPPET_HEADER_RE.match(header.strip()))


def path_of_key(key: str) -> str:
    """The source path a snippet key points at."""
    return key.split("::")[0].split(":L")[0]


def _split_into_blocks(text: str) -> list[tuple[str, str | None]]:
    """Split the note into (block_text, snippet_key | None) pairs.

    A block starts at each ``## snippet:`` header and runs until the next ``## ``
    heading of any kind. Everything else is grouped as blocks with key=None.

    A stale marker is a block of EXACTLY ONE LINE, keyed ``stale:<snippet key>``.
    It has no body by design: ``stale_hooks`` appends it at the END of the note,
    so whatever the agent writes next lands right behind it. It used to open a
    block that ran to the next ``## `` heading -- and the agent writes its turns
    under ``### ``, which does not match ``## ``. Its own prose was therefore
    swallowed into the marker, inherited the marker's key, and became untouchable
    by both passes: ``compact_judge`` skips ``stale:`` keys outright, and
    ``compact_prose`` skips anything carrying a key.

    Measured 2026-08-23 on agent f52cb5297f4f: 11 stale blocks totalling 43 522
    characters, of which the marker lines were 2 008 (4.6 %) and the agent's own
    swallowed prose 41 514 (95.4 %) -- 40.6 % of the whole note, invisible to
    compaction. One block reached 17 942 characters for a 187-character marker.
    """
    blocks: list[tuple[list[str], str | None]] = []
    current_lines: list[str] = []
    current_key: str | None = None

    for line in text.split("\n"):
        if line.startswith("## snippet-stale:"):
            if current_lines:
                blocks.append((current_lines, current_key))
            # Closed on the spot: the marker is the whole block, and the next
            # line starts a fresh prose block instead of being absorbed here.
            blocks.append(([line], "stale:" + (_extract_stale_key(line) or "")))
            current_lines = []
            current_key = None
        elif line.startswith("## snippet:"):
            if current_lines:
                blocks.append((current_lines, current_key))
            current_lines = [line]
            current_key = _extract_snippet_key(line)
        elif line.startswith("## ") and current_key is not None:
            if current_lines:
                blocks.append((current_lines, current_key))
            current_lines = [line]
            current_key = None
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append((current_lines, current_key))

    return [("\n".join(lines), key) for lines, key in blocks]
