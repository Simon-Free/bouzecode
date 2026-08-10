# [desc] Badge model for collapsed multi-line pastes (label + full text storage). [/desc]
"""Badge model for paste-aware input.

A multi-line paste is collapsed in the prompt buffer into a single-line badge
like ``[line1 (+42 lines)]``. PastedBlock holds the original full text so it can
be expanded back on submission.
"""
from __future__ import annotations

_DIM_CYAN = "\033[2;36m"
_RESET = "\033[0m"
_MAX_FIRST_LINE = 40


def paste_badge_label(full_text: str) -> str:
    """Build the inner badge label, e.g. ``line1 (+42 lines)``."""
    lines = full_text.split("\n")
    first = lines[0].strip()
    if len(first) > _MAX_FIRST_LINE:
        first = first[: _MAX_FIRST_LINE - 3] + "..."
    return f"{first} (+{len(lines)} lines)"


class TextSegment:
    __slots__ = ("text",)

    def __init__(self, text: str = ""):
        self.text = text

    def display_text(self) -> str:
        return self.text

    def plain_text(self) -> str:
        return self.text

    def display_len(self) -> int:
        return len(self.text)


class PastedBlock:
    __slots__ = ("full_text", "_display", "_n_lines")

    def __init__(self, full_text: str):
        self.full_text = full_text
        self._n_lines = full_text.count("\n") + 1
        self._display = f"[{paste_badge_label(full_text)}]"

    def display_text(self) -> str:
        return f"{_DIM_CYAN}{self._display}{_RESET}"

    def plain_text(self) -> str:
        return self.full_text

    def display_len(self) -> int:
        return len(self._display)
