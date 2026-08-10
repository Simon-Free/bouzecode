# [desc] Tests that tool_use XML inside thinking blocks is ignored by parser and renderer [/desc]
"""Tests for <thinking> block protection in XML parser and HTML renderer."""
from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser, _is_in_thinking
from bouzecode.web_v2.runtime.html_renderer.parser import parse_session
from bouzecode.web_v2.runtime.html_renderer.json_parser import strip_tool_xml


def _vt(items):
    """Split the parser's flat feed() output into (visible_text, tool_dicts)."""
    visible = "".join(x for x in items if isinstance(x, str))
    tools = [x for x in items if isinstance(x, dict)]
    return visible, tools


def _split(items):
    """Adapt feed()'s interleaved list to (visible_text, completed_tools)."""
    return (
        "".join(i for i in items if isinstance(i, str)),
        [i for i in items if isinstance(i, dict)],
    )


class TestIsInThinking:
    def test_not_in_thinking(self):
        buf = "hello world <tool_use"
        assert _is_in_thinking(buf, 12) is None

    def test_inside_thinking_block(self):
        buf = '<thinking>some <tool_use name="X" id="1">stuff\n</thinking>'
        result = _is_in_thinking(buf, 15)
        assert result is not None
        assert result[0] == len(buf)

    def test_unclosed_thinking(self):
        buf = '<thinking>some <tool_use name="X" id="1">'
        result = _is_in_thinking(buf, 15)
        assert result == (-1,)

    def test_after_thinking_block(self):
        buf = '<thinking>blah\n</thinking>\n<tool_use name="X" id="1">'
        pos = buf.index("<tool_use")
        assert _is_in_thinking(buf, pos) is None

    def test_multiple_thinking_blocks(self):
        buf = '<thinking>a\n</thinking> text \n<thinking>b <tool_use\n</thinking>'
        pos = buf.index("<tool_use")
        result = _is_in_thinking(buf, pos)
        assert result is not None
        assert result[0] == len(buf)


class TestStreamingParserThinking:
    def test_tool_inside_thinking_not_parsed(self):
        parser = XmlToolStreamParser()
        text = '<thinking>Let me think about <tool_use name="Read" id="x1"><param name="file_path">foo.py</param></tool_use>\n</thinking>'
        visible, tools = _split(parser.feed(text))
        assert tools == []
        assert "<tool_use" in visible
        assert "<thinking>" in visible

    def test_tool_after_thinking_is_parsed(self):
        parser = XmlToolStreamParser()
        text = '<thinking>planning\n</thinking>\n<tool_use name="Read" id="x1"><param name="file_path">foo.py</param></tool_use>'
        visible, tools = _split(parser.feed(text))
        assert len(tools) == 1
        assert tools[0]["name"] == "Read"
        assert "<thinking>" in visible

    def test_streaming_thinking_across_chunks(self):
        parser = XmlToolStreamParser()
        # First chunk: open thinking with tool_use start
        v1, t1 = _split(parser.feed('<thinking>some text <tool_use name="Read"'))
        assert t1 == []
        # Second chunk: close tool and thinking (close tag at line start)
        v2, t2 = _split(parser.feed(' id="x1"><param name="file_path">f</param></tool_use>\n</thinking>'))
        assert t2 == []
        # Third chunk: real tool after thinking
        v3, t3 = _split(parser.feed('\n<tool_use name="Write" id="x2"><param name="file_path">bar.py</param></tool_use>'))
        assert len(t3) == 1
        assert t3[0]["name"] == "Write"

    def test_unclosed_thinking_protects_tool(self):
        parser = XmlToolStreamParser()
        v1, t1 = _split(parser.feed('<thinking>analysis <tool_use name="Read" id="x1"><param name="file_path">x</param></tool_use>'))
        assert t1 == []


class TestParseSessionThinking:
    def test_tool_use_in_thinking_ignored(self):
        text = '<thinking>Let me use <tool_use name="Read" id="x1"><param name="file_path">foo</param></tool_use></thinking>\nSome visible text'
        blocks = parse_session(text)
        # Should not produce a ToolCall block from the thinking content
        from bouzecode.web_v2.runtime.html_renderer.parser import ToolCall
        tool_blocks = [b for b in blocks if isinstance(b, ToolCall)]
        assert tool_blocks == []

    def test_tool_use_outside_thinking_parsed(self):
        text = '<thinking>plan</thinking>\n<tool_use name="Read" id="x1"><param name="file_path">foo</param></tool_use>'
        blocks = parse_session(text)
        from bouzecode.web_v2.runtime.html_renderer.parser import ToolCall
        tool_blocks = [b for b in blocks if isinstance(b, ToolCall)]
        assert len(tool_blocks) == 1


class TestStripToolXmlThinking:
    def test_thinking_content_preserved(self):
        text = '<thinking>Let me <tool_use name="R" id="1"><param name="f">x</param></tool_use> think</thinking>\nVisible'
        result = strip_tool_xml(text)
        assert "<thinking>" in result
        assert "<tool_use" in result  # tool_use INSIDE thinking is preserved
        assert "Visible" in result

    def test_tool_outside_thinking_stripped(self):
        text = '<thinking>plan</thinking>\n<tool_use name="R" id="1"><param name="f">x</param></tool_use>\nDone'
        result = strip_tool_xml(text)
        assert "<thinking>plan</thinking>" in result
        assert "<tool_use" not in result
        assert "Done" in result
