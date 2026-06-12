"""Regression tests: backticks inside <thinking> must NOT swallow real tool_use tags.

Bug: _is_in_code() scanned from buf[0], found backticks inside a <thinking> block,
and treated them as opening a code span that extended past real <tool_use> tags.
Fix (L656-659): if code_info region_start is inside a thinking block, nullify it.
"""
import pytest

from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser


def parse_full(text: str) -> list:
    """Feed text in one shot and finalize."""
    parser = XmlToolStreamParser()
    results = parser.feed(text)
    results += parser.finalize()
    return results


def get_tools(results: list) -> list[dict]:
    return [r for r in results if isinstance(r, dict)]


class TestThinkingBackticksDoNotSwallowTools:
    """Core regression: backticks in thinking must not prevent tool_use parsing."""

    def test_unpaired_backtick_in_thinking(self):
        """Unpaired backtick in thinking followed by real tool_use."""
        text = (
            "<thinking>\n"
            "Check the variable `name and the config.\n"
            "Look at the xml_tool_protocol module.\n"
            "</thinking>\n\n"
            "Reading the file now.\n\n"
            '<tool_use name="Read" id="r1"><param name="file_path">/some/path.py</param></tool_use>\n'
            '<tool_use name="Methodology" id="m1"><param name="content">test</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 2
        assert tools[0]["name"] == "Read"
        assert tools[1]["name"] == "Methodology"

    def test_paired_backtick_cross_boundary_with_param(self):
        """Backtick in thinking whose 'pair' would be found inside a tool param."""
        text = (
            "<thinking>\n"
            'Analyzing the `foo` bar and `baz pattern.\n'
            "</thinking>\n\n"
            "Doing work.\n\n"
            '<tool_use name="Read" id="r1"><param name="file_path">/path/file.py</param></tool_use>\n'
            '<tool_use name="Edit" id="e1"><param name="file_path">/path/file.py</param>'
            '<param name="old_string">old `stuff`</param><param name="new_string">new</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 2
        assert tools[0]["name"] == "Read"
        assert tools[1]["name"] == "Edit"

    def test_fenced_code_block_in_thinking(self):
        """Fenced code block (```) inside thinking must not affect tool parsing."""
        text = (
            "<thinking>\n"
            "Here is an example:\n"
            "```python\n"
            'x = do_something()\n'
            "```\n"
            "That's the pattern.\n"
            "</thinking>\n\n"
            '<tool_use name="Bash" id="b1"><param name="command">echo hello</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 1
        assert tools[0]["name"] == "Bash"

    def test_multiple_tools_after_thinking_with_backticks(self):
        """Multiple tool_use tags after thinking with various backtick patterns."""
        text = (
            "<thinking>\n"
            "Let me check the `config` value and fix it.\n"
            'The pattern uses `<tool_use name="Example"` as template.\n'
            "</thinking>\n\n"
            "I will read the file.\n\n"
            '<tool_use name="Read" id="r1"><param name="file_path">/some/path.py</param></tool_use>\n'
            '<tool_use name="Edit" id="e1"><param name="file_path">/f.py</param>'
            '<param name="old_string">a</param><param name="new_string">b</param></tool_use>\n'
            '<tool_use name="Bash" id="b1"><param name="command">pytest</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 3
        assert [t["name"] for t in tools] == ["Read", "Edit", "Bash"]

    def test_thinking_without_angle_bracket_but_with_backtick(self):
        """CRITICAL: thinking with NO < inside but with unpaired backtick.

        This is the case that kills Option A (scan_from approach):
        - thinking has no < candidate -> scan_from stays before thinking
        - _is_in_code(start=scan_from) still sees backticks in thinking
        The fix (checking if region_start is in thinking) handles this correctly.
        """
        text = (
            "<thinking>\n"
            "I need to check the `variable name in the module.\n"
            "No angle brackets here at all, just plain text with backtick.\n"
            "</thinking>\n\n"
            '<tool_use name="Read" id="r1"><param name="file_path">/path/to/file.py</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 1
        assert tools[0]["name"] == "Read"
        assert tools[0]["id"] == "r1"

    def test_real_session_pattern_backtick_tool_use_in_thinking(self):
        """Real-world pattern: thinking mentions tool_use with backticks around it."""
        text = (
            "<thinking>\n"
            "  L'agent doit appeler `Read` pour lire le fichier.\n"
            "  Pattern: `<tool_use name=\"Read\" id=\"r1\">` suivi de params.\n"
            "  Vérifions que le fix fonctionne.\n"
            "</thinking>\n\n"
            "Je lis le fichier config.\n\n"
            '<tool_use name="Read" id="r1"><param name="file_path">/app/config.py</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 1
        assert tools[0]["name"] == "Read"

    def test_incremental_feed_backtick_in_thinking(self):
        """Streaming: thinking with backtick arrives in chunks, tool_use in later chunk."""
        text_part1 = "<thinking>\nCheck the `config"
        text_part2 = "` value.\n</thinking>\n\n"
        text_part3 = '<tool_use name="Read" id="r1"><param name="file_path">/p.py</param></tool_use>'

        parser = XmlToolStreamParser()
        r1 = parser.feed(text_part1)
        r2 = parser.feed(text_part2)
        r3 = parser.feed(text_part3)
        r4 = parser.finalize()
        all_results = r1 + r2 + r3 + r4
        tools = [r for r in all_results if isinstance(r, dict)]
        assert len(tools) == 1
        assert tools[0]["name"] == "Read"

    def test_no_thinking_backtick_still_protects_code(self):
        """Ensure fix doesn't break normal code-span protection (no thinking block)."""
        # Backtick code span containing tool_use should still be treated as text
        text = (
            "Here is an example: `<tool_use name=\"Fake\" id=\"f1\"><param name=\"x\">y</param></tool_use>`\n\n"
            '<tool_use name="Real" id="r1"><param name="file_path">/real.py</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 1
        assert tools[0]["name"] == "Real"

    def test_backtick_after_thinking_still_protects(self):
        """Backtick OUTSIDE thinking (in prose after) should still protect code spans."""
        text = (
            "<thinking>\n"
            "Simple thinking, no backticks.\n"
            "</thinking>\n\n"
            "Use the pattern `<tool_use name=\"Fake\" id=\"f1\"><param name=\"x\">y</param></tool_use>` as example.\n\n"
            '<tool_use name="Real" id="r1"><param name="file_path">/real.py</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 1
        assert tools[0]["name"] == "Real"


class TestThinkingBlockDetection:
    """Verify _is_in_thinking correctly identifies thinking regions."""

    def test_tool_use_inside_thinking_ignored(self):
        """A <tool_use> inside thinking is NOT parsed as a tool (it's prose)."""
        text = (
            "<thinking>\n"
            'I see the agent called <tool_use name="Read" id="r1"><param name="file_path">/x</param></tool_use>\n'
            "That was useful.\n"
            "</thinking>\n\n"
            '<tool_use name="Write" id="w1"><param name="file_path">/y.py</param><param name="content">hello</param></tool_use>'
        )
        tools = get_tools(parse_full(text))
        assert len(tools) == 1
        assert tools[0]["name"] == "Write"
