# [desc] Verify that a Methodology/Snippet-only batch does NOT close the session, while a real tool keeps the loop going [/desc]
"""What ends a session when the model emits only working-memory tools.

Methodology/Snippet are bookkeeping: since b83ade94 such a batch NEVER closes the
session — not even with trailing prose — it earns a continue-nudge, and the model
closes on the following plain-text reply (or by calling FinalAnswer). A batch that
also carries a real tool obviously keeps the loop going.

The old assertions here (`call_count == 1` on a meta-only batch) encoded the
pre-b83ade94 contract; the file's own TODO already doubted them, since a queue of
one response cannot distinguish "the loop broke" from "the mock ran out".
Asserting close_reason removes that ambiguity.
"""
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


METH = '<tool_use name="Methodology" id="m1"><param name="content">done</param></tool_use>'
SNIP = '<tool_use name="Snippet" id="s1"><param name="file_path">/x.py</param><param name="discard">true</param></tool_use>'
BASH = '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
CLOSE = "C'est fait."


def test_methodology_only_with_text_is_nudged_then_closes_on_plain_text():
    """Trailing prose on a Methodology-only batch does not close: the model is
    nudged once, then the plain-text reply ends the session."""
    mock = MockLLM([f"All done.\n{METH}", CLOSE])
    result = bouzecode(["Hi"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 2
    assert result.state.close_reason == "text_no_tools"


def test_methodology_and_snippet_with_text_is_nudged_then_closes_on_plain_text():
    """Methodology + Snippet is still bookkeeping — same nudge, same close path."""
    mock = MockLLM([f"Noted.\n{METH}\n{SNIP}", CLOSE])
    result = bouzecode(["Hi"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 2
    assert result.state.close_reason == "text_no_tools"


def test_methodology_plus_real_tool_continues():
    """Methodology + Bash → loop continues (Bash is not context-only)."""
    mock = MockLLM([
        f"{METH}\n{BASH}",
        CLOSE,
    ])
    result = bouzecode(["Run something"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 2
    assert CLOSE in result.last_reply
