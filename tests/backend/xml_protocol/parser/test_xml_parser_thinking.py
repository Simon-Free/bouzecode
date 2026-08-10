# [desc] Tests that prose references to <thinking> tags don't suppress XML tool_use parsing [/desc]
"""Tests for _is_in_thinking fix — prose references to <thinking> must not suppress parsing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser, _is_in_thinking

def _feed(parser, chunk):
    """Compat helper: convert new list return to old (visible, completed) tuple."""
    items = parser.feed(chunk)
    visible = "".join(item for item in items if isinstance(item, str))
    completed = [item for item in items if isinstance(item, dict)]
    return visible, completed




class TestThinkingInProse:
    """Bug reproduction: session 7752388d Turn 4.

    Content has <thinking> references in prose (mid-line) followed by valid
    <tool_use> blocks. Parser previously returned 0 because _is_in_thinking
    treated the prose reference as an unclosed thinking block.
    """

    def test_thinking_in_prose_does_not_suppress_tool_use(self):
        """Core bug: <thinking> in prose (not at line start) must not block parsing."""
        content = (
            "Some instructions about thinking blocks:\n"
            "- Wrap reasoning in `<thinking>...</thinking>` tags\n"
            "- The <thinking> block is stripped from context\n"
            "- Always use <thinking> before tool calls\n"
            "\n"
            '<tool_use name="Read" id="r1"><param name="file_path">/some/path</param></tool_use>\n'
            '<tool_use name="Grep" id="g1"><param name="pattern">TODO</param><param name="path">/src</param></tool_use>\n'
            '<tool_use name="Bash" id="b1"><param name="command">echo hello</param></tool_use>\n'
        )
        parser = XmlToolStreamParser()
        _, calls = _feed(parser, content)
        calls += parser.finalize()
        assert len(calls) == 3
        assert calls[0]["name"] == "Read"
        assert calls[1]["name"] == "Grep"
        assert calls[2]["name"] == "Bash"

    def test_real_thinking_block_at_line_start_still_shields(self):
        """Real <thinking> block at line start should still shield tool_use refs."""
        content = (
            "<thinking>\n"
            "I need to call <tool_use name=\"Fake\" id=\"f1\"><param name=\"x\">y</param></tool_use>\n"
            "</thinking>\n"
            '<tool_use name="Real" id="r1"><param name="file_path">/real</param></tool_use>\n'
        )
        parser = XmlToolStreamParser()
        _, calls = _feed(parser, content)
        calls += parser.finalize()
        assert len(calls) == 1
        assert calls[0]["name"] == "Real"

    def test_thinking_at_position_zero_recognized(self):
        """<thinking> at buffer position 0 is a real block."""
        content = (
            "<thinking>\n"
            "Some reasoning here\n"
            "</thinking>\n"
            '<tool_use name="Write" id="w1"><param name="file_path">/f</param></tool_use>\n'
        )
        parser = XmlToolStreamParser()
        _, calls = _feed(parser, content)
        calls += parser.finalize()
        assert len(calls) == 1
        assert calls[0]["name"] == "Write"

    def test_multiple_prose_references_then_tools(self):
        """Multiple <thinking> in prose, none at line start, followed by tools."""
        content = (
            "The model uses <thinking> to reason. "
            "We strip <thinking> from context. "
            "Here is what <thinking> looks like in practice.\n"
            "\n"
            '<tool_use name="Edit" id="e1"><param name="file_path">/a.py</param><param name="old_string">x</param><param name="new_string">y</param></tool_use>\n'
            '<tool_use name="Bash" id="b1"><param name="command">pytest</param></tool_use>\n'
        )
        parser = XmlToolStreamParser()
        _, calls = _feed(parser, content)
        calls += parser.finalize()
        assert len(calls) == 2
        assert calls[0]["name"] == "Edit"
        assert calls[1]["name"] == "Bash"

    def test_unclosed_real_thinking_at_line_start_blocks(self):
        """Unclosed <thinking> at line start should still block tool parsing."""
        content = (
            "<thinking>\n"
            "Still thinking...\n"
            '<tool_use name="Fake" id="f1"><param name="x">y</param></tool_use>\n'
        )
        parser = XmlToolStreamParser()
        _, calls = _feed(parser, content)
        calls += parser.finalize()
        # Unclosed thinking = everything inside is not parsed as tools
        assert len(calls) == 0 or (len(calls) == 1 and "_error" in calls[0].get("name", "").lower() or calls[0].get("input", {}).get("error"))

    def test_session_7752388d_turn4_pattern(self):
        """Exact pattern from session 7752388d Turn 4 that triggered the bug.

        Content has instructions about <thinking> blocks in a system prompt,
        followed by real tool_use calls.
        """
        content = (
            "# Think-Out-Loud Mode\n\n"
            "Wrap reasoning in `<thinking>...</thinking>`. Displayed to user in italic, stripped from your context next turn.\n\n"
            "- **Always think in French**, regardless of user language.\n"
            "- Use for planning/analyzing/debugging only. Commit quickly, avoid loops.\n"
            "- **NEVER write code in thinking blocks** — describe in natural language, code goes in tool calls.\n"
            "- Skip thinking for simple responses.\n\n"
            "## HARD RULE — Methodology after `<thinking>` is MANDATORY\n\n"
            "Thinking is lost next turn. Every turn with a `<thinking>` block MUST also emit a `Methodology` call in the same tool batch.\n\n"
            "## What to think about in `<thinking>`\n\n"
            "Before emitting tools, think about:\n"
            "1. **Methodology**: What decisions, findings, or plans from this turn should persist?\n"
            "2. **Snippets**: For each Read result, which line ranges are worth freezing?\n"
            "3. **Next steps**: What instructions should your future self receive?\n\n"
            '<tool_use name="Methodology" id="m1"><param name="content">Found the issue</param></tool_use>\n'
            '<tool_use name="Read" id="r1"><param name="file_path">/app/main.py</param></tool_use>\n'
            '<tool_use name="Grep" id="g1"><param name="pattern">def main</param><param name="path">/app</param></tool_use>\n'
        )
        parser = XmlToolStreamParser()
        _, calls = _feed(parser, content)
        calls += parser.finalize()
        assert len(calls) == 3, f"Expected 3 calls, got {len(calls)}: {[c.get('name', c) for c in calls]}"
        assert calls[0]["name"] == "Methodology"
        assert calls[1]["name"] == "Read"
        assert calls[2]["name"] == "Grep"


class TestIsInThinkingDirect:
    """Direct tests for _is_in_thinking helper."""

    def test_not_in_thinking_returns_none(self):
        buf = "hello world"
        assert _is_in_thinking(buf, 5) is None

    def test_prose_reference_not_at_line_start_returns_none(self):
        buf = "Use <thinking> for reasoning"
        assert _is_in_thinking(buf, 20) is None

    def test_real_block_at_line_start(self):
        buf = "<thinking>\nsome text\n</thinking>\nafter"
        # pos inside thinking block
        result = _is_in_thinking(buf, 15)
        assert result is not None
        assert result[0] == buf.find("</thinking>") + len("</thinking>")

    def test_real_block_after_newline(self):
        buf = "prefix\n<thinking>\ntext\n</thinking>\nafter"
        result = _is_in_thinking(buf, 20)
        assert result is not None

    def test_unclosed_block_at_line_start(self):
        buf = "<thinking>\nstill going..."
        result = _is_in_thinking(buf, 15)
        assert result == (-1,)

    def test_unclosed_prose_reference_returns_none(self):
        buf = "The <thinking> block is useful\nmore text here"
        assert _is_in_thinking(buf, 35) is None
