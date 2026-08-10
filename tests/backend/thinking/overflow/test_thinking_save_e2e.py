# [desc] Feature test: in a real bouzecode() conversation, streamed thinking reaches _build_assistant_content and is archived. [/desc]
"""Replaces the isolated unit test of `_build_assistant_content`.

Instead of calling the helper directly, we drive a real conversation through the
`bouzecode()` harness (the main agent object), mock only the LLM, and spy on the
internal seam `_build_assistant_content` to assert it is called with the right
parameters — the thinking the (mocked) model streamed and the turn's visible text.

Each turn includes a Methodology call because enforcement requires one every turn;
that is the realistic shape of a production turn.
"""
from __future__ import annotations

import bouzecode.backend.agent.loop as _loop
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

# Methodology is mandatory each turn (enforcement) — include it so the turn
# completes in a single LLM call.
_METH = '<tool_use name="Methodology" id="m1"><param name="content">noted</param></tool_use>'
_BASH = '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'


def _spy_build_assistant_content(monkeypatch):
    """Record every (at_text, thinking_parts) the loop passes to the seam, then
    delegate to the real implementation."""
    calls = []
    real = _loop._build_assistant_content

    def spy(at_text, thinking_parts):
        calls.append({"at_text": at_text, "thinking_parts": list(thinking_parts)})
        return real(at_text, thinking_parts)

    monkeypatch.setattr(_loop, "_build_assistant_content", spy)
    return calls


def test_streamed_thinking_reaches_build_and_is_archived(monkeypatch):
    """User asks → assistant thinks then answers. The streamed thinking must reach
    _build_assistant_content and land in the saved transcript; a plain turn passes
    no thinking."""
    calls = _spy_build_assistant_content(monkeypatch)

    mock = MockLLM([
        # Each reply is plain text with NO tool call — that is what closes a turn.
        # A Methodology-only batch is bookkeeping and earns a continue-nudge.
        {"thinking": ["let me reason about it"], "text": "The answer is 42."},
        "Plain follow-up.",  # backward-compat string entry: no thinking
    ])
    # recover_memory off: a tool-free turn that ALSO streamed thinking would other-
    # wise get one out-of-band Methodology recovery + continuation before closing
    # (loop.py defaults it on for XML models). This test is about archival, not
    # recovery, so the turn is left to close on its plain text.
    result = bouzecode(["What is the answer?", "thanks"], mock_llm=mock,
                       config_overrides={"recover_memory": False})

    assert len(calls) == 2
    # Turn 1: the thinking streamed by the model is handed to the seam verbatim,
    # alongside the visible answer.
    assert calls[0]["thinking_parts"] == ["let me reason about it"]
    assert "The answer is 42." in calls[0]["at_text"]
    # Turn 2: no thinking streamed → empty list.
    assert calls[1]["thinking_parts"] == []

    # The archived transcript keeps the <thinking> block on turn 1, none on turn 2.
    asst = [m for m in result.messages if m["role"] == "assistant"]
    assert "<thinking>" in asst[0]["content"]
    assert "let me reason about it" in asst[0]["content"]
    assert "<thinking>" not in asst[1]["content"]


def test_thinking_kept_in_transcript_but_stripped_from_wire(monkeypatch):
    """The saved transcript keeps the reasoning; the next turn's API payload must
    not leak it (thinking is for us, not re-sent to the model)."""
    mock = MockLLM([
        {"thinking": ["private reasoning"], "text": "Done."},
        "Bye.",
    ])
    # recover_memory off — see the note in the test above: a thinking turn without
    # tool calls would otherwise spend a recovery turn before closing.
    result = bouzecode(["go", "bye"], mock_llm=mock,
                       config_overrides={"recover_memory": False})

    asst = [m for m in result.messages if m["role"] == "assistant"][0]
    assert "<thinking>" in asst["content"] and "private reasoning" in asst["content"]

    # The wire payload the model received on turn 2 carries no <thinking>.
    turn2_payload = mock.get_messages(1)
    for msg in turn2_payload:
        content = msg.get("content", "")
        if isinstance(content, str):
            assert "<thinking>" not in content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    assert "<thinking>" not in block.get("text", "")


def test_truncated_dot_turn_keeps_thinking_drops_dot():
    """A turn truncated by max_tokens — the model emits a lone "." as visible text —
    that also carried thinking must archive the reasoning, never a stray ".".

    This is the branch where at_text == "." reaches _build_assistant_content,
    reproduced through a real conversation: turn 1 calls a tool, turn 2 is the
    truncated "." (with thinking) — a thinking-only turn auto-continues — and
    turn 3 is a clean text reply that ends the loop."""
    mock = MockLLM([
        f"{_METH}\n{_BASH}",                                          # turn 1: Methodology + Bash
        {"thinking": ["reasoning before truncation"], "text": "."},   # turn 2: truncated "." + thinking
        "All done.",                                                  # turn 3: clean text reply ends the loop
    ])
    # Turn 2 carries no tool call, so the engine makes an out-of-band side call
    # (enforcement_call, `_depth=1`) to recover a Methodology from the reasoning.
    # It is not a turn of the conversation: served from the script it would eat
    # turn 3 and shift everything by one.
    mock.side_call_response = "## Recovered\n- ran the command, output seen"
    result = bouzecode(
        ["do it"],
        mock_llm=mock,
        mock_tools={"Bash": "hello\n"},
        config_overrides={"_enforce_tests": False},
    )

    dot_turn = [
        m for m in result.messages
        if m["role"] == "assistant" and "reasoning before truncation" in m.get("content", "")
    ]
    assert len(dot_turn) == 1
    content = dot_turn[0]["content"]
    assert "<thinking>" in content          # reasoning kept
    assert content.strip() != "."           # not a bare "."
    assert not content.rstrip().endswith(".")  # no stray "." appended after the block
