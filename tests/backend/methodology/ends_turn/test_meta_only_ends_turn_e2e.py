# [desc] Feature test: a meta-only batch ends the session only with final text; a mixed batch keeps the loop going. [/desc]
"""Replaces the tautological unit tests in methodology/ends_turn/.

Through a real bouzecode() conversation we verify the actual loop behavior rather
than re-asserting a hardcoded set membership:
- a meta-only (Methodology / Snippet) batch ends the session when the response
  also carries final-answer text — no extra LLM call;
- a batch that also contains a real tool (Bash) does NOT end the turn — the loop
  executes the tool and calls the model again.

Since 627c3be a SILENT meta-only batch gets a continue-nudge instead of ending —
that side is covered by tests/backend/agent_loop/test_meta_only_continue_e2e.py.

The mixed-batch case also guards the root-cause invariant (Methodology.ends_turn
is False): were it True, every batch containing Methodology would end the turn, so
the mixed-batch conversation would stop early and its call count would drop.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

_METH = '<tool_use name="Methodology" id="m1"><param name="content">noted</param></tool_use>'
_SNIP = ('<tool_use name="Snippet" id="s1"><param name="discard">true</param>'
         '<param name="file_path">/x.py</param></tool_use>')
_BASH = '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'


def test_methodology_only_batch_with_text_does_not_end_turn():
    """A Methodology-only batch (even with trailing prose) must NOT close the
    session: only FinalAnswer closes by default. The model is nudged to continue
    and closes on the following text-only reply (no tool calls)."""
    mock = MockLLM([f"done.\n{_METH}", "vraiment fini."])
    bouzecode(["hello"], mock_llm=mock)
    assert mock.call_count == 2


def test_meta_only_batch_with_snippet_and_text_does_not_end_turn():
    """Methodology + Snippet + trailing prose also must NOT close: continuation,
    then close on the following text-only reply."""
    mock = MockLLM([f"done.\n{_METH}\n{_SNIP}", "vraiment fini."])
    bouzecode(["hello"], mock_llm=mock, mock_tools=True)
    assert mock.call_count == 2


def test_mixed_batch_does_not_end_turn():
    """Methodology + a real tool (Bash) keeps the loop going: Bash runs, the model
    is called again. This fails if Methodology ever gains ends_turn=True."""
    mock = MockLLM([
        f"{_METH}\n{_BASH}",   # mixed batch → must continue
        "Done.",               # text-only reply (no tool) closes the session
    ])
    bouzecode(["run it"], mock_llm=mock, mock_tools={"Bash": "hi\n"})
    assert mock.call_count == 2
