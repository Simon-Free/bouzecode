# [desc] Tests that cache_control breakpoints stay within Anthropic's per-request budget across methodology scenarios
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that cache_control breakpoints stay within Anthropic's per-request budget across methodology scenarios</param></tool_use> [/desc]
"""Anthropic caps cache_control breakpoints per request (4 on official API).

Count all cache_control blocks (system + messages) across every methodology
scenario: no methodology, first turn, unchanged, appended.
"""
from __future__ import annotations

from bouzecode.backend.context_manager.methodology import build_methodology_system_blocks
from bouzecode.backend.agent.providers.conversion import messages_to_anthropic


_CC = {"type": "ephemeral"}
_BUDGET = 4


def _count_cache_control(blocks):
    return sum(
        1 for b in blocks
        if isinstance(b, dict) and b.get("cache_control") is not None
    )


def _count_msg_cache_control(payload):
    n = 0
    for m in payload:
        c = m.get("content")
        if isinstance(c, list):
            n += _count_cache_control(c)
    return n


def _full_payload_breakpoints(methodology, snapshot, msgs):
    """Count cache_control breakpoints as dispatch.stream would build them."""
    sys_blocks = [
        {"type": "text", "text": "SYS", "cache_control": _CC},
        {"type": "text", "text": "TOOLS", "cache_control": _CC},
    ]
    meth_blocks, _ = build_methodology_system_blocks(methodology, snapshot, _CC)
    sys_blocks += meth_blocks
    sys_blocks.append({"type": "text", "text": "volatile"})
    anth_msgs = messages_to_anthropic(msgs, cache_last=True)
    return _count_cache_control(sys_blocks) + _count_msg_cache_control(anth_msgs)


_BASE_MSGS = [
    {"role": "user", "content": "turn1 q"},
    {"role": "assistant", "content": "turn1 a", "tool_calls": []},
    {"role": "user", "content": "turn2 q"},
]


def test_breakpoints_no_methodology_within_budget():
    n = _full_payload_breakpoints("", "", _BASE_MSGS)
    assert n <= _BUDGET, f"{n} breakpoints exceeds budget {_BUDGET}"


def test_breakpoints_first_turn_methodology_within_budget():
    n = _full_payload_breakpoints("## User\nhi", "", _BASE_MSGS)
    assert n <= _BUDGET, f"{n} breakpoints exceeds budget {_BUDGET}"


def test_breakpoints_unchanged_methodology_within_budget():
    text = "## User\nhi\n"
    n = _full_payload_breakpoints(text, text, _BASE_MSGS)
    assert n <= _BUDGET, f"{n} breakpoints exceeds budget {_BUDGET}"


def test_breakpoints_appended_methodology_within_budget():
    old = "## User\nhi\n"
    current = old + "\n## snippet\nbody\n"
    n = _full_payload_breakpoints(current, old, _BASE_MSGS)
    assert n <= _BUDGET, f"{n} breakpoints exceeds budget {_BUDGET}"


def test_breakpoints_replaced_methodology_within_budget():
    n = _full_payload_breakpoints("## new\n", "## old\n", _BASE_MSGS)
    assert n <= _BUDGET, f"{n} breakpoints exceeds budget {_BUDGET}"


def test_breakpoints_first_turn_no_message_anchor_within_budget():
    """First user loop → no previous-loop anchor → no message cache_control."""
    msgs = [{"role": "user", "content": "only turn"}]
    n = _full_payload_breakpoints("## content\n", "", msgs)
    assert n <= _BUDGET, f"{n} breakpoints exceeds budget {_BUDGET}"
