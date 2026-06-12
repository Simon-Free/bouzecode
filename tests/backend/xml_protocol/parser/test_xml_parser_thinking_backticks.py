"""
Regression tests: backticks inside <thinking> blocks must NOT swallow
subsequent real <tool_use> tags.

Bug: _is_in_code() scans from buf[0], finds backtick(s) in a <thinking> block,
the "closing" backtick falls after real <tool_use> tags -> feed() skips them
-> 0 tools parsed -> session dies ("emission avalee").

Fix: at L656-659 in parser.py, if code_info region_start is inside a thinking
block, code_info is nullified.
"""

import pytest

from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser


def parse_all(text: str) -> list:
    """Feed text in one shot and finalize."""
    parser = XmlToolStreamParser()
    results = parser.feed(text)
    results += parser.finalize()
    return results


def tools_from(results: list) -> list[dict]:
    return [r for r in results if isinstance(r, dict)]


def text_from(results: list) -> str:
    return "".join(r for r in results if isinstance(r, str))


class TestThinkingBackticksDoNotSwallowTools:
    """Core regression: backticks in thinking must not prevent tool parsing."""

    def test_unpaired_backtick_in_thinking(self):
        """Unpaired backtick in thinking followed by tool_use -> tool parsed."""
        text = (
            "<thinking>\n"
            "Check the variable `name and the config.\n"
            "Look at the xml_tool_protocol module.\n"
            "</thinking>\n\n"
            "Reading the file now.\n\n"
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">/some/path.py</param>'
            "</tool_use>\n"
            '<tool_use name="Methodology" id="m1">'
            '<param name="content">test</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 2, f"Expected 2 tools, got {len(tools)}"
        assert tools[0]["name"] == "Read"
        assert tools[1]["name"] == "Methodology"

    def test_paired_backtick_crossing_boundary(self):
        """Backtick opened in thinking, closed in tool param -> tools parsed."""
        text = (
            "<thinking>\n"
            "Analyzing the `foo` bar and `baz pattern.\n"
            "</thinking>\n\n"
            "Doing work.\n\n"
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">/path/file.py</param>'
            "</tool_use>\n"
            '<tool_use name="Edit" id="e1">'
            '<param name="file_path">/path/file.py</param>'
            '<param name="old_string">old `stuff`</param>'
            '<param name="new_string">new</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 2, f"Expected 2 tools, got {len(tools)}"
        assert tools[0]["name"] == "Read"
        assert tools[1]["name"] == "Edit"

    def test_fenced_code_block_in_thinking(self):
        """Fenced code block inside thinking must not affect tool parsing."""
        text = (
            "<thinking>\n"
            "Here is the code:\n"
            "```python\n"
            'def foo():\n'
            '    return "<tool_use>"\n'
            "```\n"
            "That was the code.\n"
            "</thinking>\n\n"
            "Now acting.\n\n"
            '<tool_use name="Bash" id="b1">'
            '<param name="command">echo hello</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 1
        assert tools[0]["name"] == "Bash"

    def test_multiple_tools_after_thinking_with_backticks(self):
        """Multiple tools after thinking with various backtick patterns."""
        text = (
            "<thinking>\n"
            "Let me check the `config` value and fix it.\n"
            "The pattern uses `<tool_use name=\"Example\"` as template.\n"
            "</thinking>\n\n"
            "I will read the file.\n\n"
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">/some/path.py</param>'
            "</tool_use>\n"
            '<tool_use name="Methodology" id="m1">'
            '<param name="content">note</param>'
            "</tool_use>\n"
            '<tool_use name="Edit" id="e1">'
            '<param name="file_path">/x.py</param>'
            '<param name="old_string">a</param>'
            '<param name="new_string">b</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 3
        assert [t["name"] for t in tools] == ["Read", "Methodology", "Edit"]

    def test_thinking_no_angle_bracket_with_unpaired_backtick(self):
        """
        CRITICAL: thinking with NO '<' inside but with unpaired backtick.
        This is the case that kills 'Option A' (passing scan_from to _is_in_code).
        If the thinking has no '<', scan_from doesn't advance past it,
        so a naive start= fix still sees the backtick.
        The fix at L656-659 handles this correctly by checking if backtick
        region_start is inside thinking regardless of scan_from position.
        """
        text = (
            "<thinking>\n"
            "The variable `name should be checked.\n"
            "No angle brackets here, just backticks.\n"
            "</thinking>\n\n"
            "Acting now.\n\n"
            '<tool_use name="Write" id="w1">'
            '<param name="file_path">/tmp/test.py</param>'
            '<param name="content">hello</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 1, f"Expected 1 tool, got {len(tools)}"
        assert tools[0]["name"] == "Write"

    def test_tool_use_inside_thinking_not_parsed(self):
        """tool_use text INSIDE thinking is correctly NOT parsed as tool."""
        text = (
            "<thinking>\n"
            'I see `<tool_use name="Fake" id="f1">` in the docs.\n'
            "</thinking>\n\n"
            "Real action:\n\n"
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">/real.py</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        # Only the real tool outside thinking should be parsed
        assert len(tools) == 1
        assert tools[0]["name"] == "Read"
        assert tools[0]["id"] == "r1"

    def test_no_thinking_backtick_still_blocks(self):
        """Without thinking, an unpaired backtick SHOULD still block tool parsing.
        This is the correct existing behavior - backticks in prose (not thinking)
        legitimately indicate code regions where tool_use patterns should be ignored."""
        text = (
            "Let me check the `name variable.\n\n"
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">/path.py</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        # Unpaired backtick in prose = unclosed inline code -> tool NOT parsed
        assert len(tools) == 0

    def test_thinking_triple_backtick_inline(self):
        """Triple backtick (not at line start) in thinking does not block."""
        text = (
            "<thinking>\n"
            "The syntax is ``` something ``` in the docs.\n"
            "</thinking>\n\n"
            '<tool_use name="Glob" id="g1">'
            '<param name="pattern">**/*.py</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 1
        assert tools[0]["name"] == "Glob"


class TestThinkingBackticksStreamingChunks:
    """Verify fix works with chunked streaming (not just one-shot)."""

    def test_chunked_thinking_then_tool(self):
        """Thinking with backtick arrives in chunks, then tool_use."""
        parser = XmlToolStreamParser()
        all_results = []

        # Chunk 1: start of thinking with backtick
        all_results += parser.feed("<thinking>\nCheck `config")
        # Chunk 2: rest of thinking
        all_results += parser.feed(" value.\n</thinking>\n\n")
        # Chunk 3: tool
        all_results += parser.feed(
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">/x.py</param>'
            "</tool_use>"
        )
        all_results += parser.finalize()

        tools = tools_from(all_results)
        assert len(tools) == 1
        assert tools[0]["name"] == "Read"

    def test_chunked_unpaired_backtick_in_thinking(self):
        """Unpaired backtick in thinking, streamed in small chunks."""
        parser = XmlToolStreamParser()
        all_results = []

        chunks = [
            "<thinking>\n",
            "Variable `name is important.\n",
            "No closing backtick here.\n",
            "</thinking>\n\n",
            "Now acting.\n\n",
            '<tool_use name="Bash" id="b1">',
            '<param name="command">ls</param>',
            "</tool_use>",
        ]
        for chunk in chunks:
            all_results += parser.feed(chunk)
        all_results += parser.finalize()

        tools = tools_from(all_results)
        assert len(tools) == 1
        assert tools[0]["name"] == "Bash"


class TestRealSessionReplay:
    """Replay patterns from real fatal sessions."""

    def test_session_pattern_backtick_tool_use_in_thinking(self):
        """
        Pattern from session 4a3c76e559da msg 18:
        thinking block contains backtick-quoted tool_use patterns.
        The tool_use inside thinking must NOT be parsed.
        """
        text = (
            "<thinking>\n"
            "  L'utilisateur veut un `<tool_use name=\"Read\"` pattern.\n"
            "  Je dois utiliser `Read` pour lire le fichier.\n"
            "  Le format est `<tool_use name=\"X\" id=\"y\">...</tool_use>`.\n"
            "</thinking>\n\n"
            "Je lis le fichier.\n\n"
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">/project/src/main.py</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 1
        assert tools[0]["name"] == "Read"

    def test_long_thinking_multiple_backticks_then_tools(self):
        """
        Pattern from fatal sessions: long thinking with many backticks
        and code references, followed by multiple tool calls.
        """
        text = (
            "<thinking>\n"
            "  Analysons le problème. Le fichier `parser.py` contient la\n"
            "  fonction `_is_in_code` qui scanne les backticks. Le bug est\n"
            "  que `_is_in_code(buf, pos)` commence à buf[0] et trouve\n"
            "  les backticks du thinking. L'appel `feed()` à la ligne 656\n"
            "  vérifie `code_info` mais ne sait pas que le backtick est\n"
            "  dans un thinking. Solution: vérifier avec `_is_in_thinking`.\n"
            "  \n"
            "  Plan:\n"
            "  1. Modifier L656 pour nullifier code_info si dans thinking\n"
            "  2. Écrire des tests\n"
            "  3. Valider avec le script de repro\n"
            "</thinking>\n\n"
            "J'implémente le fix.\n\n"
            '<tool_use name="Methodology" id="m1">'
            '<param name="content">Fix identified</param>'
            "</tool_use>\n"
            '<tool_use name="Edit" id="e1">'
            '<param name="file_path">/src/parser.py</param>'
            '<param name="old_string">old</param>'
            '<param name="new_string">new</param>'
            "</tool_use>\n"
            '<tool_use name="RunPythonTest" id="t1">'
            '<param name="targets">["tests/test_parser.py"]</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 3
        assert [t["name"] for t in tools] == ["Methodology", "Edit", "RunPythonTest"]

    def test_indented_thinking_content_backticks(self):
        """
        Real pattern: thinking content is indented (2 spaces per spec),
        backticks reference code. Tools follow after closing tag.
        """
        text = (
            "<thinking>\n"
            "  Le `scan_from` ne couvre pas ce cas.\n"
            "  Option (b): borner start de `_is_in_code` à fin_du_dernier_thinking.\n"
            "  Mais Option A est insuffisante car `scan_from` n'avance pas.\n"
            "</thinking>\n\n"
            '<tool_use name="Grep" id="g1">'
            '<param name="pattern">_is_in_code</param>'
            '<param name="path">/src</param>'
            "</tool_use>"
        )
        results = parse_all(text)
        tools = tools_from(results)
        assert len(tools) == 1
        assert tools[0]["name"] == "Grep"
