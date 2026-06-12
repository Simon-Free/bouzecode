"""Tests for meta_only_nudges telemetry counter.

Verifies that the session state tracks how many times the
'Methodology-only' nudge is injected during a conversation.
"""

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM


METH = '<tool_use name="Methodology" id="m1"><param name="content">noted</param></tool_use>'


def test_meta_only_nudge_increments_counter():
    """A silent Methodology-only turn triggers the nudge and increments counter."""
    mock = MockLLM([
        # Turn 1: Methodology-only, no text → triggers nudge
        METH,
        # Turn 2 (after nudge): real work + close
        f'Done.\n{METH}\n<tool_use name="Bash" id="b1"><param name="command">echo ok</param></tool_use>',
        # Turn 3: final answer closing the session
        f"All done.\n{METH}",
    ])
    result = bouzecode(["do something"], mock_llm=mock)
    assert result.state.meta_only_nudges == 1


def test_no_meta_only_nudge_stays_zero():
    """A conversation with no Methodology-only turns has counter == 0."""
    mock = MockLLM([
        # Turn 1: real work
        f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>',
        # Turn 2: final answer
        f"Finished.\n{METH}",
    ])
    result = bouzecode(["do it"], mock_llm=mock)
    assert result.state.meta_only_nudges == 0
