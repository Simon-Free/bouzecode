# [desc] Segment model and terminal rendering for paste-aware input with collapsible pasted blocks. [/desc]
"""Segment model for paste-aware input.

TextSegment: normal typed text, editable char-by-char.
PastedBlock: collapsed paste badge, deleted atomically with one Backspace.
"""
from __future__ import annotations
import re
import shutil
import sys

_DIM_CYAN = "\033[2;36m"
_RESET = "\033[0m"
_ERASE_TO_END = "\033[J"
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

_prev_cursor_line: int = 0


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
        lines = full_text.split("\n")
        self._n_lines = len(lines)
        first = lines[0].strip()
        if len(first) > 40:
            first = first[:37] + "..."
        self._display = f"[{first} (+{self._n_lines} lines)]"

    def display_text(self) -> str:
        return f"{_DIM_CYAN}{self._display}{_RESET}"

    def plain_text(self) -> str:
        return self.full_text

    def display_len(self) -> int:
        return len(self._display)


Segment = TextSegment | PastedBlock


# ── Rendering & cursor helpers ────────────────────────────────────────────

def visual_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def reset_render_state() -> None:
    global _prev_cursor_line
    _prev_cursor_line = 0


def _advance(row: int, col: int, ch: str, term_width: int) -> tuple[int, int]:
    if ch == "\n":
        return row + 1, 0
    col += 1
    if col >= term_width:
        return row + 1, 0
    return row, col


def _walk_positions(prompt: str, segments: list[Segment], cursor_pos: int, term_width: int):
    """Walk prompt + segment display chars, tracking row/col for cursor and end.

    Accounts for both embedded '\\n' in TextSegment text and terminal wrapping.
    Returns (cursor_row, cursor_col, end_row).
    """
    prompt_plain = _ANSI_RE.sub("", prompt)
    row = col = 0
    for ch in prompt_plain:
        row, col = _advance(row, col, ch, term_width)

    cur_row = cur_col = None
    seen = 0
    for seg in segments:
        if isinstance(seg, PastedBlock):
            chars = seg._display
        else:
            chars = seg.text
        for ch in chars:
            if seen == cursor_pos:
                cur_row, cur_col = row, col
            seen += 1
            row, col = _advance(row, col, ch, term_width)
    if cur_row is None:
        cur_row, cur_col = row, col
    return cur_row, cur_col, row


def render_line(prompt: str, segments: list[Segment], cursor_pos: int):
    global _prev_cursor_line

    parts = [prompt]
    for seg in segments:
        parts.append(seg.display_text())
    content = "".join(parts)

    term_width = shutil.get_terminal_size().columns

    if _prev_cursor_line > 0:
        sys.stdout.write(f"\033[{_prev_cursor_line}A")
    try:
        sys.stdout.write(f"\r{_ERASE_TO_END}{content}")
    except UnicodeEncodeError:
        content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        sys.stdout.write(f"\r{_ERASE_TO_END}{content}")

    cursor_line, cursor_col, end_line = _walk_positions(prompt, segments, cursor_pos, term_width)

    lines_up = end_line - cursor_line
    if lines_up > 0:
        sys.stdout.write(f"\033[{lines_up}A")
    sys.stdout.write("\r")
    if cursor_col > 0:
        sys.stdout.write(f"\033[{cursor_col}C")

    _prev_cursor_line = cursor_line
    sys.stdout.flush()


def cursor_to_segment(segments: list[Segment], cursor_pos: int):
    pos = 0
    for i, seg in enumerate(segments):
        seg_len = seg.display_len()
        if cursor_pos <= pos + seg_len:
            return i, cursor_pos - pos
        pos += seg_len
    if segments:
        return len(segments) - 1, segments[-1].display_len()
    return 0, 0


def total_display_len(segments: list[Segment]) -> int:
    return sum(seg.display_len() for seg in segments)


def result_text(segments: list[Segment]) -> str:
    return "".join(seg.plain_text() for seg in segments).strip()


def merge_adjacent_text(segments: list[Segment]):
    i = 0
    while i < len(segments) - 1:
        if isinstance(segments[i], TextSegment) and isinstance(segments[i + 1], TextSegment):
            segments[i].text += segments[i + 1].text
            segments.pop(i + 1)
        else:
            i += 1


def split_and_insert_block(segments, seg_i, offset, paste_text):
    seg = segments[seg_i]
    before = seg.text[:offset]
    after = seg.text[offset:]
    block = PastedBlock(paste_text)
    segments[seg_i:seg_i + 1] = [TextSegment(before), block, TextSegment(after)]


def recalc_cursor_after_insert(segments, orig_seg_i, orig_offset, paste_text):
    pos = 0
    for seg in segments:
        if isinstance(seg, PastedBlock) and seg.full_text == paste_text:
            return pos + seg.display_len()
        pos += seg.display_len()
    return pos
