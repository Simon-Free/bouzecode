# [desc] Tests paste_input badge model: TextSegment, PastedBlock display/plain text, and badge label formatting
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests paste_input badge model: TextSegment, PastedBlock display/plain text, and badge label formatting</param></tool_use> [/desc]
"""Tests for the paste_input badge model."""
from bouzecode.ui.paste_input.segments import (
    TextSegment,
    PastedBlock,
    paste_badge_label,
)


def test_text_segment():
    s = TextSegment("hello")
    assert s.display_text() == "hello"
    assert s.plain_text() == "hello"
    assert s.display_len() == 5


def test_paste_badge_label():
    assert paste_badge_label("line1\nline2\nline3") == "line1 (+3 lines)"


def test_paste_badge_label_truncates_long_first_line():
    label = paste_badge_label("a" * 60 + "\nline2")
    assert "..." in label
    assert label.endswith("(+2 lines)")


def test_pasted_block():
    text = "line1\nline2\nline3"
    b = PastedBlock(text)
    assert b.plain_text() == text
    assert "+3 lines" in b.display_text()
    assert b.display_len() > 0
    # display_len must not count ANSI codes
    assert "\033" not in str(b.display_len())


def test_pasted_block_long_first_line():
    text = "a" * 60 + "\nline2\nline3"
    b = PastedBlock(text)
    assert "..." in b._display
    assert b.display_len() < 60
