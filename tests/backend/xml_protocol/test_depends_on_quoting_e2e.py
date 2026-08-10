# [desc] Conversation-level proof that the depends_on quoting slip and prose mentions of <tool_use> no longer burn a turn. [/desc]
"""What the two XML fixes change for a real conversation.

Measured on 743 production payloads (docs/investigations/xml_tool_call_failures.md):
the model chains its calls with `depends_on="["m1"]"`, the parser rejected the whole
block, and the turn was spent on an error message instead of the work. And when the
model merely TALKED about `<tool_use>`, the parser executed its prose — same cost.
Both must now be free.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">plan</param></tool_use>'
PARSE_ERROR = "ERROR parsing your tool call XML"


def _results_of(result, tool_name):
    return [m for m in result.messages
            if m.get("role") == "tool" and m.get("name") == tool_name]


def _parse_error_round_trips(result):
    return [m for m in result.messages if PARSE_ERROR in str(m.get("content", ""))]


def test_a_chained_bash_written_with_quoted_brackets_actually_runs():
    """The model chains Bash after its Methodology using `depends_on="["m1"]"`."""
    batch = (
        f"{METH}\n"
        '<tool_use name="Bash" id="b1" depends_on="["m1"]">'
        '<param name="command">echo hi</param></tool_use>'
    )
    result = bouzecode(
        ["lance la commande"],
        mock_llm=MockLLM([batch, "fait, la commande a tourne."]),
    )

    assert [m["content"] for m in _results_of(result, "Bash")] == ["hi"]
    assert not _parse_error_round_trips(result)


def test_talking_about_the_tool_use_tag_costs_no_error_round_trip():
    """The model explains the protocol in prose; nothing runs, nothing is answered."""
    prose = "Le parseur confond un `<tool_use>` cite en prose avec un vrai appel."
    result = bouzecode(["explique le bug"], mock_llm=MockLLM([prose]))

    assert not _parse_error_round_trips(result)
    assert "prose" in result.last_reply


def test_a_bash_cut_mid_command_is_reported_and_never_executed():
    """A truncated call stays an error: half a command must not run."""
    cut = f"{METH}\n" '<tool_use name="Bash" id="b1"><param name="command">echo hi && rm -rf /tm'
    result = bouzecode(
        ["lance la commande"],
        mock_llm=MockLLM([cut, "je corrige mon XML."]),
    )

    assert not _results_of(result, "Bash")
    assert _parse_error_round_trips(result), "a truncated call must still be reported"
