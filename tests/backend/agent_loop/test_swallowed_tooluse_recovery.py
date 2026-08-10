# [desc] Tests that <tool_use> swallowed by a ``` fence / <thinking> is re-prompted, not closed. [/desc]
"""Swallowed tool_use recovery:

A model may emit real <tool_use> XML wrapped in a ``` fence (or inside <thinking>).
The XML parser treats both regions as inert visible text (by design, so prose can
show example markup), so the turn parses to ZERO tool calls. Without a guard the
headless loop reads "text, no tools" and closes prematurely (FinalAnswer nudge) —
the intended edits never run. The guard detects the swallowed emission and asks the
model to re-emit raw.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">todo</param></tool_use>'
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         '<param name="answer">Done.</param></tool_use>')
BASH = '<tool_use name="Bash" id="b1"><param name="command">echo ok</param></tool_use>'

HEADLESS_CFG = {"close_requires_final_answer": True, "test_enforcement": False, "enforce_methodology": False}


def _user_msgs(result):
    return [str(m.get("content", "")) for m in result.messages if m.get("role") == "user"]


def _swallow_nudges(result):
    return [m for m in _user_msgs(result)
            if "System Automated" in m and "BRUT" in m]


def test_fenced_tool_use_is_recovered_not_closed():
    """A tool_use wrapped in a ``` fence parses to 0 calls → guard re-prompts → the
    model re-emits raw and the session completes via FinalAnswer (not a premature close)."""
    mock = MockLLM([
        f"```\nJ'applique le fix.\n{BASH}\n```",   # swallowed by the fence
        f"{BASH}",                                  # re-emitted raw after the nudge
        f"{METH}\n{FINAL}",                         # clean close
    ])
    result = bouzecode(["fais le fix"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer"
    nudges = _swallow_nudges(result)
    assert len(nudges) >= 1, "swallowed <tool_use> should trigger a re-emit nudge"


def test_tool_use_inside_thinking_is_recovered():
    """A <tool_use> emitted inside a <thinking> block is inert → guard re-prompts."""
    mock = MockLLM([
        {"thinking": [f"Je vais lancer : {BASH}"], "text": "", "stop_reason": "end_turn"},
        f"{BASH}",
        f"{METH}\n{FINAL}",
    ])
    result = bouzecode(["fais le fix"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer"
    assert len(_swallow_nudges(result)) >= 1


def test_plain_text_without_tooluse_markup_does_not_trigger_guard():
    """A normal text reply (no <tool_use ... name=> markup) must NOT hit the swallow
    guard — it follows the standard headless FinalAnswer nudge path."""
    mock = MockLLM([
        "Voilà ma réponse finale.",   # no tool markup at all
        f"{METH}\n{FINAL}",
    ])
    result = bouzecode(["question"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer"
    assert _swallow_nudges(result) == [], "plain text must not trigger the swallow guard"
