# [desc] Tests that tool_use blocks with content but no <param> tags produce parse errors. [/desc]
"""Test that tool_use blocks with content but no <param> tags produce errors."""
import pytest
from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser, _parse_block

def _feed(parser, chunk):
    """Compat helper: convert new list return to old (visible, completed) tuple."""
    items = parser.feed(chunk)
    visible = "".join(item for item in items if isinstance(item, str))
    completed = [item for item in items if isinstance(item, dict)]
    return visible, completed




def _feed_all(text: str, chunk_size: int = 50) -> list[dict]:
    parser = XmlToolStreamParser()
    tool_calls = []
    for i in range(0, len(text), chunk_size):
        parts, calls = _feed(parser, text[i:i + chunk_size])
        tool_calls.extend(calls)
    tool_calls.extend(parser.finalize())
    return tool_calls


class TestNoParamTagsError:
    """tool_use with body content but no <param> tags should return an error."""

    def test_read_without_params(self):
        xml = '<tool_use name="Read" id="r1">some/file/path.py75100</tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert calls[0]["name"] == "_XmlParseError"

    def test_snippet_without_params(self):
        xml = '<tool_use name="Snippet" id="s1">C:\\path\\file.py[[1,50]]my label</tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert calls[0]["name"] == "_XmlParseError"

    def test_methodology_without_params(self):
        xml = '<tool_use name="Methodology" id="m1">replaceThis is my methodology content</tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert calls[0]["name"] == "_XmlParseError"

    def test_error_message_mentions_param(self):
        xml = '<tool_use name="Read" id="r1">file.py</tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert "param" in calls[0]["input"]["_error"].lower()

    def test_empty_body_is_valid(self):
        """A tool_use with empty body is valid (tool with no required params)."""
        xml = '<tool_use name="SomeTool" id="x1"></tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert calls[0]["name"] == "SomeTool"
        assert calls[0]["input"] == {}

    def test_whitespace_only_body_is_valid(self):
        """Whitespace-only body should be treated as empty (valid)."""
        xml = '<tool_use name="SomeTool" id="x1">   \n  </tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert calls[0]["name"] == "SomeTool"

    def test_valid_params_still_work(self):
        """Normal tool_use with proper param tags should still work."""
        xml = '<tool_use name="Read" id="r1"><param name="file_path">foo.py</param></tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert calls[0]["name"] == "Read"
        assert calls[0]["input"]["file_path"] == "foo.py"

    def test_mixed_content_with_some_params(self):
        """If at least one param is found, extra text around it is OK (existing behavior)."""
        xml = '<tool_use name="Read" id="r1">junk<param name="file_path">foo.py</param>more junk</tool_use>'
        calls = _feed_all(xml)
        assert len(calls) == 1
        assert calls[0]["name"] == "Read"
        assert calls[0]["input"]["file_path"] == "foo.py"
