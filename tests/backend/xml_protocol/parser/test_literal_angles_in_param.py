"""Tests for literal angle brackets inside <param> values WITHOUT CDATA wrapping.

Regression tests for ticket FIX3 — session_105839 MSG #87, #92, #99, #105.
Post-FIX2 the parser silently swallows tool calls whose param values contain
literal angle brackets. The fix must make these parse correctly.
"""
from __future__ import annotations

import pytest


def _parser():
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    return XmlToolStreamParser()


def _feed(parser, chunk):
    """Compat helper: convert list return to (visible, completed) tuple."""
    items = parser.feed(chunk)
    visible = "".join(item for item in items if isinstance(item, str))
    completed = [item for item in items if isinstance(item, dict)]
    return visible, completed


# ---------------------------------------------------------------------------
# Case 1: MSG #87/#105 pattern — Edit with literal <param> in old_string
# The model emits an Edit whose old_string contains 'no <param>' literally.
# Parser must NOT interpret the inner </param> as closing the outer param.
# ---------------------------------------------------------------------------
class TestLiteralAnglesInParamValues:

    def test_edit_with_literal_param_tag_in_value(self):
        """old_string contains literal angle-bracket 'param' — must parse as 1 Edit."""
        p = _parser()
        # Build XML by parts to avoid any confusion in THIS file's own parsing
        raw = (
            '<tool_use name="Edit" id="e1">'
            '<param name="file_path">C:\\test.py</param>'
            '<param name="old_string">assert desc("_XmlParseError", {"_error": "no <param>"}) == \\\n'
            '    "Malformed"</param>'
            '<param name="new_string">assert desc("_XmlParseError", {"_error": "no <param>"}) == \\\n'
            '    "Malformed"\n\ndef test_final():\n    pass</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        # Must produce exactly 1 valid Edit (not _XmlParseError, not 0 tools)
        assert len(completed) == 1, f"Expected 1 tool, got {len(completed)}: {completed}"
        assert completed[0]["name"] == "Edit"
        assert completed[0]["id"] == "e1"
        assert 'no <param>' in completed[0]["input"]["old_string"]

    def test_two_tools_first_simple_second_has_angles(self):
        """Methodology + Edit where Edit has literal angles — both must parse."""
        p = _parser()
        raw = (
            '<tool_use name="Methodology" id="m1">'
            '<param name="content">Adding tests</param>'
            '</tool_use>\n'
            '<tool_use name="Edit" id="e1">'
            '<param name="file_path">C:\\test.py</param>'
            '<param name="old_string">no <param> here</param>'
            '<param name="new_string">no <param> here\nextra line</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        assert len(completed) == 2, f"Expected 2 tools, got {len(completed)}: {[c.get('name') for c in completed]}"
        assert completed[0]["name"] == "Methodology"
        assert completed[1]["name"] == "Edit"
        assert '<param>' in completed[1]["input"]["old_string"]

    def test_literal_br_tag_in_param_value(self):
        """Value contains <br> and <br/> — common HTML the model might emit."""
        p = _parser()
        raw = (
            '<tool_use name="Write" id="w1">'
            '<param name="file_path">out.html</param>'
            '<param name="content">Hello<br>World<br/>End</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        assert len(completed) == 1
        assert completed[0]["name"] == "Write"
        assert completed[0]["input"]["content"] == "Hello<br>World<br/>End"

    def test_literal_tool_use_tag_in_param_value(self):
        """Value contains a full tool_use example (bare, no CDATA).
        The existing test_bare_nested_tool_use_inside_param tests this partly,
        but we verify the exact session pattern here."""
        p = _parser()
        inner_example = '<tool_use name="Read" id="r1"><param name="file_path">x.py</param></tool_use>'
        raw = (
            '<tool_use name="Edit" id="e1">'
            '<param name="file_path">doc.md</param>'
            f'<param name="new_string">Example:\n{inner_example}\nEnd</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        assert len(completed) == 1
        assert completed[0]["name"] == "Edit"
        assert inner_example in completed[0]["input"]["new_string"]

    def test_multiple_angle_brackets_no_cdata(self):
        """Value with several stray < and > that are NOT valid XML tags."""
        p = _parser()
        raw = (
            '<tool_use name="Write" id="w1">'
            '<param name="file_path">test.txt</param>'
            '<param name="content">if x < 10 and y > 5:\n    print("<ok>")</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        assert len(completed) == 1
        assert completed[0]["name"] == "Write"
        assert 'x < 10' in completed[0]["input"]["content"]
        assert '<ok>' in completed[0]["input"]["content"]

    def test_silent_swallow_must_not_happen(self):
        """If the parser cannot parse a tool_use block, it MUST emit _XmlParseError,
        never silently drop it (the post-FIX2 regression)."""
        p = _parser()
        # A truly ambiguous case: value contains literal </param> which is
        # identical to the closing tag. Without CDATA this is the ONE case
        # that remains unparseable — but it must NOT be silently swallowed.
        raw = (
            '<tool_use name="Edit" id="e1">'
            '<param name="file_path">a.py</param>'
            '<param name="old_string">x</param>'
            '<param name="new_string">print("</param>")</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        # We accept either:
        # (a) Parser somehow figures it out (unlikely without CDATA), OR
        # (b) Parser emits _XmlParseError — NOT 0 tools
        assert len(completed) >= 1, (
            "Parser silently swallowed a tool_use block — this is the post-FIX2 regression!"
        )


class TestLiteralAnglesWithThinking:
    """Verify thinking blocks containing angle brackets don't break subsequent tools."""

    def test_thinking_with_angle_brackets_then_tool(self):
        """Thinking mentions <param> literally, followed by a real tool_use."""
        p = _parser()
        raw = (
            '<thinking>\n'
            '  The <param> tag needs CDATA wrapping when it contains angles.\n'
            '  Example: <tool_use name="X"><param name="y">val</param></tool_use>\n'
            '</thinking>\n\n'
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">test.py</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        assert len(completed) == 1
        assert completed[0]["name"] == "Read"

    def test_thinking_with_fenced_code_angles_then_tool(self):
        """Thinking has fenced code block with angle brackets — tool after must parse."""
        p = _parser()
        raw = (
            '<thinking>\n'
            '  The file ends with:\n'
            '  ```\n'
            '  assert desc("_XmlParseError", {"_error": "no <param>"}) == \\\n'
            '      "Malformed tool call"\n'
            '  ```\n'
            '</thinking>\n\n'
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">test.py</param>'
            '</tool_use>'
        )
        _, completed = _feed(p, raw)
        assert len(completed) == 1
        assert completed[0]["name"] == "Read"
