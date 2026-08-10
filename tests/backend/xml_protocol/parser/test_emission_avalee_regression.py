# [desc] Regression tests verifying backticks in thinking blocks don't swallow subsequent tool_use emissions. [/desc]
"""Regression tests: thinking-block backticks must not swallow tool_use emissions."""
from __future__ import annotations

import pytest

from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser


def _feed_all(text: str):
    """Feed entire text to a fresh parser, return (visible_text, completed_tools)."""
    parser = XmlToolStreamParser()
    items = parser.feed(text)
    items.extend(parser.finalize())
    visible = "".join(item for item in items if isinstance(item, str))
    completed = [item for item in items if isinstance(item, dict)]
    return visible, completed


def _tool_xml(name, tid, **params):
    """Build a tool_use XML string."""
    po = "<" + "param"
    pc = "</" + "param>"
    px = "".join(f'{po} name="{k}">{v}{pc}' for k, v in params.items())
    return f'<tool_use name="{name}" id="{tid}">{px}</tool_use>'


class TestEmissionAvaleeRegression:
    """Bug: _is_in_code scanning from buffer start treats backticks in thinking
    as opening code spans that extend past real tool_use tags."""

    def test_paired_backticks_in_thinking(self):
        """Paired backticks in thinking must not affect tool parsing."""
        tool = _tool_xml("Read", "r1", file_path="/some/path.py")
        text = (
            "<thinking>\n"
            "Let me check the `config` value and fix it.\n"
            'The pattern uses `<tool_use name="Example"` as template.\n'
            "</thinking>\n\n"
            "I will read the file.\n\n"
            f"{tool}"
        )
        _, completed = _feed_all(text)
        assert len(completed) == 1
        assert completed[0]["name"] == "Read"

    def test_unpaired_backtick_in_thinking(self):
        """Unpaired backtick in thinking must not swallow tools after thinking."""
        tool = _tool_xml("Read", "r1", file_path="/some/path.py")
        text = (
            "<thinking>\n"
            "Check the variable `name and the config.\n"
            "Look at the xml_tool_protocol module.\n"
            "</thinking>\n\n"
            "Reading the file now.\n\n"
            f"{tool}"
        )
        _, completed = _feed_all(text)
        assert len(completed) == 1
        assert completed[0]["name"] == "Read"

    def test_backtick_cross_boundary_thinking_to_tool_param(self):
        """Backtick opened in thinking whose 'closing' match is inside a tool param
        must not swallow tools."""
        tool1 = _tool_xml("Read", "r1", file_path="/path/file.py")
        tool2 = _tool_xml("Edit", "e1", file_path="/path/file.py",
                          old_string="old `stuff`", new_string="new")
        text = (
            "<thinking>\n"
            "Analyzing the `foo` bar and `baz pattern.\n"
            "</thinking>\n\n"
            "Doing work.\n\n"
            f"{tool1}\n{tool2}"
        )
        _, completed = _feed_all(text)
        assert len(completed) == 2
        assert completed[0]["name"] == "Read"
        assert completed[1]["name"] == "Edit"

    def test_multiple_unpaired_backticks_in_thinking(self):
        """Multiple unpaired backticks in thinking must not affect tool parsing."""
        tool1 = _tool_xml("Read", "r1", file_path="/a.py")
        tool2 = _tool_xml("Methodology", "m1", content="note")
        text = (
            "<thinking>\n"
            "  The `variable is used in `another context\n"
            "  and then `more backticks without closing\n"
            "</thinking>\n\n"
            f"{tool1}\n{tool2}"
        )
        _, completed = _feed_all(text)
        assert len(completed) == 2

    def test_fenced_code_in_thinking_with_tool_template(self):
        """Fenced code block in thinking containing tool_use template must not
        consume the real tool_use after thinking."""
        tool = _tool_xml("Bash", "b1", command="echo hi")
        text = (
            "<thinking>\n"
            "Example:\n"
            "```\n"
            '<tool_use name="Fake" id="f1"><param name="x">y</param></tool_use>\n'
            "```\n"
            "</thinking>\n\n"
            f"{tool}"
        )
        _, completed = _feed_all(text)
        assert len(completed) == 1
        assert completed[0]["name"] == "Bash"


class TestStreamingThinkingHoldBuffer:
    """Bug: when <thinking> tag is split across chunks (e.g. chunk_size=2),
    the hold-buffer didn't retain the partial tag, causing thinking content
    to be emitted as visible text. Backticks in thinking then activated
    _in_inline_code which swallowed subsequent tool_use tags."""

    def _feed_chunked(self, text: str, chunk_size: int):
        """Feed text in fixed-size chunks, return (visible_text, completed_tools)."""
        parser = XmlToolStreamParser()
        items = []
        for i in range(0, len(text), chunk_size):
            items.extend(parser.feed(text[i:i + chunk_size]))
        items.extend(parser.finalize())
        visible = "".join(item for item in items if isinstance(item, str))
        completed = [item for item in items if isinstance(item, dict)]
        return visible, completed

    @pytest.mark.parametrize("chunk_size", [1, 2, 3, 4, 5, 7, 8, 10, 13, 50])
    def test_thinking_with_backticks_streamed(self, chunk_size):
        """Thinking block with inline backticks must not swallow tools at any chunk size."""
        tool1 = _tool_xml("Methodology", "m1", content="some note")
        tool2 = _tool_xml("AskUserQuestion", "q1", question="Which option?")
        text = (
            "<thinking>\n"
            "  J'ai maintenant la reponse claire. Dans `list_agents()` (L181-187):\n"
            "\n"
            "  ```python\n"
            '  out.append({"name": name, "tools": list(defn.tools), "skills": []})\n'
            "  ```\n"
            "\n"
            "  Pour le profil \"coder\" :\n"
            "  - `defn.tools` = [] (default_factory=list)\n"
            "  - `\"skills\": []` - hardcode a vide\n"
            "  L'option 2 est plus flexible. Demandons a l'utilisateur.\n"
            "</thinking>\n"
            "\n"
            "J'ai identifie la cause du bug. Dans `definitions.py`, le profil ne declare **aucun tool** (il utilise le default `[]`). "
            "Et dans `profiles.py` L185-187, `skills` est hardcode a `[]`.\n"
            "\n"
            "Le frontend recoit donc `tools: [], skills: []` - rien n'est coche.\n"
            "\n"
            f"{tool1}\n{tool2}"
        )
        _, completed = self._feed_chunked(text, chunk_size)
        assert len(completed) == 2, f"chunk_size={chunk_size}: found {[c['name'] for c in completed]}"
        assert completed[0]["name"] == "Methodology"
        assert completed[1]["name"] == "AskUserQuestion"

    @pytest.mark.parametrize("chunk_size", [2, 3, 5, 7])
    def test_thinking_tag_split_across_chunks(self, chunk_size):
        """<thinking> tag split by chunk boundaries must still be recognized."""
        tool = _tool_xml("Read", "r1", file_path="/some/file.py")
        text = (
            "<thinking>\n"
            "  Check the `config` variable.\n"
            "</thinking>\n"
            "\n"
            "Reading the file with `Read` tool.\n"
            "\n"
            f"{tool}"
        )
        _, completed = self._feed_chunked(text, chunk_size)
        assert len(completed) == 1, f"chunk_size={chunk_size}: found {[c['name'] for c in completed]}"
        assert completed[0]["name"] == "Read"
