# [desc] Tests for filtering out <tool_result> XML blocks from the stream parser output. [/desc]
"""Tests for <tool_result> filtering in XmlToolStreamParser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser


def test_tool_result_single_chunk_stripped():
    """A complete <tool_result> in one chunk is swallowed."""
    parser = XmlToolStreamParser()
    result = parser.feed('Hello <tool_result id="r1" tokens="5">some content</tool_result> world')
    visible = "".join(s for s in result if isinstance(s, str))
    assert "tool_result" not in visible
    assert "some content" not in visible
    assert "Hello" in visible
    assert "world" in visible


def test_tool_result_cross_chunk():
    """A <tool_result> split across chunks is swallowed."""
    parser = XmlToolStreamParser()
    r1 = parser.feed('Before <tool_result id="x1" tok')
    r2 = parser.feed('ens="10">hidden text</tool_resu')
    r3 = parser.feed('lt> After')
    visible = "".join(s for s in r1 + r2 + r3 if isinstance(s, str))
    assert "tool_result" not in visible
    assert "hidden text" not in visible
    assert "Before" in visible
    assert "After" in visible


def test_tool_result_multiple_blocks():
    """Multiple <tool_result> blocks are all swallowed."""
    parser = XmlToolStreamParser()
    text = (
        'Text1 <tool_result id="a" tokens="1">AAA</tool_result> '
        'Text2 <tool_result id="b" tokens="2">BBB</tool_result> Text3'
    )
    result = parser.feed(text)
    visible = "".join(s for s in result if isinstance(s, str))
    assert "AAA" not in visible
    assert "BBB" not in visible
    assert "Text1" in visible
    assert "Text2" in visible
    assert "Text3" in visible


def test_tool_result_does_not_affect_tool_use():
    """tool_use blocks are still parsed normally alongside tool_result."""
    parser = XmlToolStreamParser()
    text = (
        '<tool_result id="r1" tokens="5">result</tool_result>'
        '<tool_use name="Read" id="t1"><param name="path">foo.py</param></tool_use>'
    )
    result = parser.feed(text)
    tools = [item for item in result if isinstance(item, dict)]
    texts = [item for item in result if isinstance(item, str)]
    assert len(tools) == 1
    assert tools[0]["name"] == "Read"
    visible = "".join(texts)
    assert "result" not in visible


def test_tool_result_partial_tag_buffered():
    """A partial <tool_result at end of chunk is buffered, not emitted."""
    parser = XmlToolStreamParser()
    r1 = parser.feed("Hello <tool_resul")
    r2 = parser.feed('t id="x" tokens="1">hidden</tool_result> end')
    visible = "".join(s for s in r1 + r2 if isinstance(s, str))
    assert "tool_resul" not in visible
    assert "hidden" not in visible
    assert "Hello" in visible
    assert "end" in visible


def test_tool_result_not_a_tag():
    """<tool_resulting (no space/>) should pass through as text."""
    parser = XmlToolStreamParser()
    result = parser.feed("The <tool_resulting stuff is fine")
    visible = "".join(s for s in result if isinstance(s, str))
    assert "tool_resulting" in visible


def test_thinking_still_works():
    """<thinking> blocks still work after the change."""
    parser = XmlToolStreamParser()
    result = parser.feed("Before <thinking>internal</thinking> After")
    visible = "".join(s for s in result if isinstance(s, str))
    assert "Before" in visible
    assert "internal" in visible  # thinking is emitted as visible text
    assert "After" in visible
