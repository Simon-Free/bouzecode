# [desc] Tests that ThinkingStreamParser handles <thinking>/</thinking> tags appearing mid-line as content, not block delimiters
# <tool_use name="FinalAnswer" id="x1"><param name="answer">Tests that ThinkingStreamParser handles <thinking>/</thinking> tags appearing mid-line as content, not block delimiters</param></tool_use> [/desc]
"""Test that ThinkingStreamParser handles <thinking>/</thinking> inside content."""
import pytest
from bouzecode.backend.agent.thinking_parser import ThinkingStreamParser


def collect(parser, text):
    """Feed text in one go and finalize."""
    results = parser.feed(text)
    results.extend(parser.finalize())
    return results


def collect_chunked(parser, text, chunk_size=3):
    """Feed text in small chunks and finalize."""
    results = []
    for i in range(0, len(text), chunk_size):
        results.extend(parser.feed(text[i:i + chunk_size]))
    results.extend(parser.finalize())
    return results


class TestThinkingInsideContent:
    """Bug: </thinking> mid-line in content should NOT close the block."""

    def test_close_tag_midline_does_not_close(self):
        """A </thinking> that's NOT at start of line should be treated as content."""
        text = '<thinking>\nHello </thinking> world\n</thinking>\n'
        parser = ThinkingStreamParser()
        results = collect(parser, text)
        # Should get one thinking block with full content including the mid-line </thinking>
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        full_thinking = "".join(thinking_parts)
        assert "</thinking> world" in full_thinking
        # The text after should be minimal (just newline or empty)
        text_parts = [r[1] for r in results if r[0] == "text"]
        full_text = "".join(text_parts)
        assert "world" not in full_text

    def test_close_tag_midline_chunked(self):
        """Same test but with chunked feeding."""
        text = '<thinking>\nHello </thinking> world\n</thinking>\n'
        parser = ThinkingStreamParser()
        results = collect_chunked(parser, text, chunk_size=5)
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        full_thinking = "".join(thinking_parts)
        assert "</thinking> world" in full_thinking

    def test_open_tag_midline_does_not_open(self):
        """A <thinking> mid-line in normal text should not open a thinking block."""
        text = 'Hello <thinking> world\n<thinking>\nactual thinking\n</thinking>\n'
        parser = ThinkingStreamParser()
        results = collect(parser, text)
        text_parts = [r[1] for r in results if r[0] == "text"]
        full_text = "".join(text_parts)
        # The mid-line <thinking> should be treated as regular text
        assert "<thinking> world" in full_text
        # But the real thinking block should still work
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        full_thinking = "".join(thinking_parts)
        assert "actual thinking" in full_thinking

    def test_multiple_fake_close_tags(self):
        """Multiple </thinking> mid-line should all be treated as content."""
        text = '<thinking>\nUse </thinking> and </thinking> in text\n</thinking>\n'
        parser = ThinkingStreamParser()
        results = collect(parser, text)
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        full_thinking = "".join(thinking_parts)
        assert "Use </thinking> and </thinking> in text" in full_thinking


class TestNormalBehavior:
    """Regression: normal behavior still works."""

    def test_simple_thinking_block(self):
        text = '<thinking>\nHello world\n</thinking>\nSome text after'
        parser = ThinkingStreamParser()
        results = collect(parser, text)
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        text_parts = [r[1] for r in results if r[0] == "text"]
        assert "Hello world" in "".join(thinking_parts)
        assert "Some text after" in "".join(text_parts)

    def test_thinking_at_very_start(self):
        """<thinking> at position 0 (start of stream) should work."""
        text = '<thinking>\nContent\n</thinking>\n'
        parser = ThinkingStreamParser()
        results = collect(parser, text)
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        assert "Content" in "".join(thinking_parts)

    def test_chunked_normal(self):
        text = '<thinking>\nHello\n</thinking>\nWorld'
        parser = ThinkingStreamParser()
        results = collect_chunked(parser, text, chunk_size=4)
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        text_parts = [r[1] for r in results if r[0] == "text"]
        assert "Hello" in "".join(thinking_parts)
        assert "World" in "".join(text_parts)

    def test_finalize_unclosed(self):
        """Unclosed thinking block should be flushed as thinking on finalize."""
        text = '<thinking>\nUnclosed content'
        parser = ThinkingStreamParser()
        results = collect(parser, text)
        thinking_parts = [r[1] for r in results if r[0] == "thinking"]
        assert "Unclosed content" in "".join(thinking_parts)
