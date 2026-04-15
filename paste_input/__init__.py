# [desc] Package entry point: exports paste-aware input reader with collapsible multi-line paste blocks. [/desc]
"""Paste-aware input with collapsible pasted blocks.

When the user pastes multi-line text, it collapses into a compact badge:
  [pasted lines (+42 lines)]
The badge is deletable atomically with a single Backspace press.
"""
from __future__ import annotations
import sys

from paste_input.segments import TextSegment, PastedBlock, Segment
from paste_input.segments import (
    render_line, cursor_to_segment, total_display_len,
    result_text, merge_adjacent_text, split_and_insert_block,
    recalc_cursor_after_insert,
)

PASTE_BADGE_THRESHOLD = 2  # min lines to trigger collapsing

_history: list[str] = []
_MAX_HISTORY = 200


def add_history(text: str):
    if text.strip() and (not _history or _history[-1] != text):
        _history.append(text)
        if len(_history) > _MAX_HISTORY:
            _history.pop(0)


def get_history() -> list[str]:
    return _history


def read_input_with_paste_blocks(prompt: str) -> str:
    """Read a line of input with paste-block collapsing support.

    Returns the full text (with pasted content expanded) ready for submission.
    """
    if not sys.stdin.isatty():
        return input(prompt)

    if sys.platform == "win32":
        from paste_input.windows import read_input_windows
        return read_input_windows(prompt)
    else:
        from paste_input.unix import read_input_unix
        return read_input_unix(prompt)
