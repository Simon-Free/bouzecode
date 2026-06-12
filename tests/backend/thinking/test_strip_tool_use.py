# [desc] Tests XML tool_use stripping and edge cases (CDATA, backticks, combined with thinking tags) [/desc]
"""Tests for strip_tool_use_xml function in thinking_parser.py."""

from bouzecode.backend.agent.thinking_parser import strip_tool_use_xml, strip_thinking_tags


class TestStripToolUseXml:
    def test_simple_tool_use_removed(self):
        content = (
            'Some text before\n'
            '<tool_use name="Read" id="r1"><param name="file_path">/path</param></tool_use>\n'
            'Some text after'
        )
        result = strip_tool_use_xml(content)
        assert "Some text before" in result
        assert "Some text after" in result
        assert "<tool_use" not in result

    def test_multiple_tool_use_removed(self):
        content = (
            '<tool_use name="Read" id="r1"><param name="file_path">/a</param></tool_use>\n'
            '<tool_use name="Grep" id="g1"><param name="pattern">x</param><param name="path">/b</param></tool_use>\n'
        )
        result = strip_tool_use_xml(content)
        assert "<tool_use" not in result

    def test_no_tool_use_unchanged(self):
        content = "Just regular prose text with no XML."
        result = strip_tool_use_xml(content)
        assert result == content

    def test_tool_use_with_cdata(self):
        cdata_content = "<![CDATA[some content with </tool_use> inside]]>"
        content = (
            '<tool_use name="Write" id="w1">'
            '<param name="file_path">/test.py</param>'
            '<param name="content">' + cdata_content + '</param>'
            '</tool_use>\n'
            'visible text after'
        )
        result = strip_tool_use_xml(content)
        assert "visible text after" in result
        assert "<tool_use" not in result

    def test_prose_mentioning_tool_use_in_backticks_preserved(self):
        content = "The format uses `<tool_use>` tags for tool calls."
        result = strip_tool_use_xml(content)
        assert "tool_use" in result

    def test_empty_content(self):
        assert strip_tool_use_xml("") == ""

    def test_combined_strip(self):
        content = (
            '<tool_use name="Methodology" id="m1">'
            '<param name="content"><![CDATA[some notes]]></param>'
            '</tool_use>\n'
            'The answer is 42.'
        )
        cleaned = strip_tool_use_xml(content)
        cleaned = strip_thinking_tags(cleaned)
        assert "The answer is 42" in cleaned
        assert "<tool_use" not in cleaned
