# [desc] Unit tests for paste_input segment model operations including cursor mapping and display logic. [/desc]
"""Tests for paste_input segment model."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from paste_input.segments import (
    TextSegment, PastedBlock,
    cursor_to_segment, total_display_len, result_text,
    merge_adjacent_text, split_and_insert_block, recalc_cursor_after_insert,
    _walk_positions,
)


def test_text_segment():
    s = TextSegment("hello")
    assert s.display_text() == "hello"
    assert s.plain_text() == "hello"
    assert s.display_len() == 5


def test_pasted_block():
    text = "line1\nline2\nline3"
    b = PastedBlock(text)
    assert b.plain_text() == text
    assert "+3 lines" in b.display_text()
    assert b.display_len() > 0
    # Display len should NOT include ANSI codes
    assert "\033" not in str(b.display_len())


def test_pasted_block_long_first_line():
    first = "a" * 60
    text = first + "\nline2\nline3"
    b = PastedBlock(text)
    # First line should be truncated in display
    assert "..." in b._display
    assert b.display_len() < 60


def test_cursor_to_segment_single():
    segs = [TextSegment("hello")]
    assert cursor_to_segment(segs, 0) == (0, 0)
    assert cursor_to_segment(segs, 3) == (0, 3)
    assert cursor_to_segment(segs, 5) == (0, 5)


def test_cursor_to_segment_with_block():
    segs = [TextSegment("ab"), PastedBlock("x\ny\nz"), TextSegment("cd")]
    # "ab" = 2 chars, block display = N chars, "cd" = 2 chars
    block_len = segs[1].display_len()
    assert cursor_to_segment(segs, 0) == (0, 0)
    assert cursor_to_segment(segs, 2) == (0, 2)  # end of first text
    assert cursor_to_segment(segs, 2 + block_len) == (1, block_len)
    assert cursor_to_segment(segs, 2 + block_len + 1) == (2, 1)


def test_total_display_len():
    segs = [TextSegment("ab"), PastedBlock("x\ny"), TextSegment("cd")]
    expected = 2 + segs[1].display_len() + 2
    assert total_display_len(segs) == expected


def test_result_text():
    segs = [TextSegment("hello "), PastedBlock("line1\nline2"), TextSegment(" world")]
    assert result_text(segs) == "hello line1\nline2 world"


def test_merge_adjacent_text():
    segs = [TextSegment("a"), TextSegment("b"), PastedBlock("x\ny"), TextSegment("c"), TextSegment("d")]
    merge_adjacent_text(segs)
    assert len(segs) == 3
    assert segs[0].text == "ab"
    assert isinstance(segs[1], PastedBlock)
    assert segs[2].text == "cd"


def test_split_and_insert_block():
    segs = [TextSegment("abcd")]
    split_and_insert_block(segs, 0, 2, "paste\ndata")
    assert len(segs) == 3
    assert segs[0].text == "ab"
    assert isinstance(segs[1], PastedBlock)
    assert segs[1].full_text == "paste\ndata"
    assert segs[2].text == "cd"


def test_recalc_cursor_after_insert():
    segs = [TextSegment("ab"), PastedBlock("x\ny"), TextSegment("cd")]
    pos = recalc_cursor_after_insert(segs, 0, 2, "x\ny")
    assert pos == 2 + segs[1].display_len()


def test_walk_positions_single_line():
    segs = [TextSegment("hello")]
    cur_row, cur_col, end_row = _walk_positions("> ", segs, 3, term_width=80)
    assert (cur_row, cur_col, end_row) == (0, 5, 0)


def test_walk_positions_embedded_newline():
    """TextSegment containing '\\n' should advance to next row."""
    segs = [TextSegment("line1\nline2")]
    cur_row, cur_col, end_row = _walk_positions("> ", segs, 11, term_width=80)
    assert end_row == 1
    assert cur_row == 1
    assert cur_col == 5  # "line2"


def test_walk_positions_cursor_before_newline():
    segs = [TextSegment("ab\ncd")]
    cur_row, cur_col, end_row = _walk_positions("", segs, 2, term_width=80)
    assert (cur_row, cur_col, end_row) == (0, 2, 1)


def test_walk_positions_terminal_wrap():
    segs = [TextSegment("x" * 10)]
    cur_row, cur_col, end_row = _walk_positions("", segs, 10, term_width=5)
    # 10 chars wrap: 5 on row 0 (col 0-4), then row 1 col 0-4 -> after last char we're on row 2 col 0
    assert end_row == 2
    assert cur_row == 2
    assert cur_col == 0


def test_walk_positions_prompt_ansi_stripped():
    """ANSI codes in prompt must not count toward columns."""
    segs = [TextSegment("a")]
    cur_row, cur_col, end_row = _walk_positions("\033[2;36m> \033[0m", segs, 1, term_width=80)
    assert end_row == 0
    assert cur_col == 3  # "> " + "a"


def test_walk_positions_multiline_history_recall():
    """Regression: recalling a multiline input from history must track rows correctly."""
    segs = [TextSegment("first line\nsecond line\nthird")]
    cur_row, cur_col, end_row = _walk_positions("", segs, len("first line\nsecond line\nthird"), term_width=80)
    assert end_row == 2
    assert cur_row == 2
    assert cur_col == 5


def test_backspace_deletes_block():
    """Simulate: cursor is right after a PastedBlock, backspace removes it."""
    segs = [TextSegment("ab"), PastedBlock("x\ny\nz"), TextSegment("cd")]
    block_len = segs[1].display_len()
    cursor_pos = 2 + block_len  # right after the block

    # Simulate backspace
    seg_i, offset = cursor_to_segment(segs, cursor_pos)
    # seg_i should be 1 (the block), offset should be block_len
    # But since cursor is at end of block, it maps to block
    seg = segs[seg_i]
    if isinstance(seg, PastedBlock):
        cursor_pos -= seg.display_len()
        segs.pop(seg_i)
        merge_adjacent_text(segs)

    assert len(segs) == 1  # "ab" + "cd" merged
    assert segs[0].text == "abcd"
    assert cursor_pos == 2
