"""Tests for pathological thinking parser cases.

Cases:
(a) Thought content mentions </thinking> literally
(b) Tool call XML inside a thought
(c) Multiple consecutive thoughts
(d) Unclosed thinking tag (stream ends without </thinking>)
"""
import pytest

from bouzecode.backend.agent.thinking_parser import (
    ThinkingStreamParser,
    strip_thinking_tags,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _feed_all(text: str) -> list[tuple[str, str]]:
    """Feed entire text to parser and finalize, return merged results."""
    p = ThinkingStreamParser()
    results = p.feed(text)
    results += p.finalize()
    return results


def _feed_chunked(text: str, chunk_size: int = 5) -> list[tuple[str, str]]:
    """Feed text in small chunks, simulating streaming."""
    p = ThinkingStreamParser()
    results: list[tuple[str, str]] = []
    for i in range(0, len(text), chunk_size):
        results += p.feed(text[i:i + chunk_size])
    results += p.finalize()
    return results


def _concat_by_type(results: list[tuple[str, str]]) -> dict[str, str]:
    """Merge consecutive same-type tuples into a dict."""
    merged: dict[str, str] = {"thinking": "", "text": ""}
    for kind, content in results:
        merged[kind] += content
    return merged


# ===========================================================================
# (a) Thought content mentions </thinking> tag literally
# ===========================================================================

class TestThinkingMentionsCloseTag:
    """The thought CONTENT discusses </thinking> — must not close prematurely."""

    THOUGHT_WITH_MENTION = (
        "<thinking>\n"
        "  The model uses </thinking> to close its thought block.\n"
        "  We need to handle this correctly.\n"
        "</thinking>\n"
        "Actual response text here."
    )

    def test_stream_full_feed(self):
        """</thinking> inside a sentence (not alone on line) must not close thought."""
        results = _feed_all(self.THOUGHT_WITH_MENTION)
        merged = _concat_by_type(results)
        # The thinking content should include the mention of </thinking>
        assert "The model uses </thinking>" in merged["thinking"]
        assert "Actual response text here." in merged["text"]

    def test_stream_chunked(self):
        """Same test but with chunked streaming."""
        results = _feed_chunked(self.THOUGHT_WITH_MENTION, chunk_size=7)
        merged = _concat_by_type(results)
        assert "The model uses </thinking>" in merged["thinking"]
        assert "Actual response text here." in merged["text"]

    def test_close_tag_at_col0_in_content(self):
        """</thinking> at col 0 but with trailing text is NOT a real close."""
        text = (
            "<thinking>\n"
            "</thinking> is the close tag for thoughts.\n"
            "More thinking here.\n"
            "</thinking>\n"
            "Response."
        )
        results = _feed_all(text)
        merged = _concat_by_type(results)
        # The first </thinking> has trailing text, so it should NOT close
        assert "</thinking> is the close tag" in merged["thinking"]
        assert "More thinking here." in merged["thinking"]
        assert "Response." in merged["text"]

    def test_strip_thinking_tags_with_mention(self):
        """strip_thinking_tags should handle content mentioning the tag."""
        text = (
            "<thinking>\n"
            "  The parser looks for </thinking> at line start.\n"
            "  This is tricky.\n"
            "</thinking>\n"
            "Final answer."
        )
        result = strip_thinking_tags(text)
        assert result == "Final answer."


# ===========================================================================
# (b) Tool call XML appears inside a thought
# ===========================================================================

class TestToolCallInsideThought:
    """Tool use XML inside thinking block should be treated as thinking content."""

    THOUGHT_WITH_TOOL = (
        "<thinking>\n"
        "  Let me think about this.\n"
        '  <tool_use name="Read" id="r1"><param name="file_path">/tmp/x.py</param></tool_use>\n'
        "  That was just an example.\n"
        "</thinking>\n"
        "Here is my response."
    )

    def test_stream_tool_in_thought(self):
        """tool_use XML inside thought stays as thinking content."""
        results = _feed_all(self.THOUGHT_WITH_TOOL)
        merged = _concat_by_type(results)
        assert '<tool_use name="Read"' in merged["thinking"]
        assert "Here is my response." in merged["text"]

    def test_stream_tool_in_thought_chunked(self):
        results = _feed_chunked(self.THOUGHT_WITH_TOOL, chunk_size=10)
        merged = _concat_by_type(results)
        assert '<tool_use name="Read"' in merged["thinking"]
        assert "Here is my response." in merged["text"]

    def test_strip_thinking_tags_with_tool(self):
        result = strip_thinking_tags(self.THOUGHT_WITH_TOOL)
        assert "Here is my response." == result


# ===========================================================================
# (c) Multiple consecutive thoughts
# ===========================================================================

class TestMultipleThoughts:
    """Parser handles multiple thinking blocks in sequence."""

    MULTI = (
        "<thinking>\n"
        "  First thought.\n"
        "</thinking>\n"
        "Text between thoughts.\n"
        "<thinking>\n"
        "  Second thought.\n"
        "</thinking>\n"
        "Final text."
    )

    def test_stream_multiple(self):
        results = _feed_all(self.MULTI)
        thinking_parts = [c for k, c in results if k == "thinking"]
        text_parts = [c for k, c in results if k == "text"]
        thinking_all = "".join(thinking_parts)
        text_all = "".join(text_parts)
        assert "First thought." in thinking_all
        assert "Second thought." in thinking_all
        assert "Text between thoughts." in text_all
        assert "Final text." in text_all

    def test_strip_multiple(self):
        result = strip_thinking_tags(self.MULTI)
        assert "First thought." not in result
        assert "Second thought." not in result
        assert "Text between thoughts." in result
        assert "Final text." in result


# ===========================================================================
# (d) Unclosed thinking tag
# ===========================================================================

class TestUnclosedThinking:
    """Unclosed <thinking> tag (e.g. stream interrupted)."""

    UNCLOSED = (
        "<thinking>\n"
        "  Started thinking but stream ended abruptly."
    )

    def test_stream_unclosed(self):
        """Unclosed thought: finalize emits remaining as thinking."""
        results = _feed_all(self.UNCLOSED)
        merged = _concat_by_type(results)
        assert "Started thinking" in merged["thinking"]
        # No text output since everything is inside unclosed thought
        assert merged["text"] == ""

    def test_strip_unclosed(self):
        """strip_thinking_tags removes everything from <thinking> to end."""
        text = "Preamble.\n<thinking>\n  Unclosed block."
        result = strip_thinking_tags(text)
        assert "Preamble." in result
        assert "Unclosed" not in result
