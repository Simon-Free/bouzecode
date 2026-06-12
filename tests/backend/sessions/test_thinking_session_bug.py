# [desc] Tests that thinking blocks survive session save while tool_use XML is correctly stripped [/desc]
"""Tests for the _clean_message fix: thinking blocks must survive session save.

The renderer (html_renderer/renderer.py) needs <thinking> tags in the saved
session JSON to render them with .thinking CSS class (italic, grey border).
Only tool_use XML should be stripped.
"""
from bouzecode.backend.agent.thinking_parser import strip_tool_use_xml


def _clean_message_logic(content: str) -> str:
    """Reproduce the fixed _clean_message logic from commands/session.py."""
    cleaned = strip_tool_use_xml(content)
    if not cleaned:
        cleaned = "."
    return cleaned


def test_thinking_only_preserved():
    """Thinking-only content is preserved (not replaced by '.')."""
    content = "<thinking>\nSome deep thought here\nAnother line\n</thinking>"
    result = _clean_message_logic(content)
    assert "<thinking>" in result
    assert "Some deep thought" in result
    assert result != "."


def test_mixed_content_preserves_thinking():
    """Content with text + thinking keeps both parts."""
    content = "Here is my answer.\n<thinking>\nLet me think about this...\n</thinking>\nMore text."
    result = _clean_message_logic(content)
    assert "<thinking>" in result
    assert "Let me think" in result
    assert "Here is my answer" in result
    assert "More text" in result


def test_tool_xml_stripped_correctly():
    """Tool XML is still stripped (renderer uses tool_calls field instead)."""
    content = '<tool_use name="Read" id="r1"><param name="file_path">foo.py</param></tool_use>'
    result = _clean_message_logic(content)
    assert "<tool_use" not in result


def test_tool_only_becomes_dot():
    """Tool-only messages (no text, no thinking) become '.' as fallback."""
    content = '<tool_use name="Read" id="r1"><param name="file_path">foo.py</param></tool_use>'
    result = _clean_message_logic(content)
    assert result == "."


def test_thinking_with_tool_xml():
    """Thinking preserved even when mixed with tool XML."""
    content = (
        "<thinking>\nPlanning the edit...\n</thinking>\n"
        "Here is my response.\n"
        '<tool_use name="Edit" id="e1"><param name="file_path">x.py</param></tool_use>'
    )
    result = _clean_message_logic(content)
    assert "<thinking>" in result
    assert "Planning the edit" in result
    assert "Here is my response" in result
    assert "<tool_use" not in result


def test_renderer_can_find_thinking_after_clean():
    """The renderer regex can match thinking in cleaned content."""
    import re
    _THINKING_RE = re.compile(r'(?:^|\n)[ \t]*<thinking>[ \t]*\n?(.*?)\n?[ \t]*</thinking>[ \t]*(?:\n|$)', re.DOTALL)

    content = "<thinking>\nAnalyzing...\n</thinking>\nMy answer."
    cleaned = _clean_message_logic(content)
    segments = _THINKING_RE.split(cleaned)
    # segments should have 3 parts: before, thinking content, after
    assert len(segments) == 3
    assert "Analyzing" in segments[1]
    assert "My answer" in segments[2]
