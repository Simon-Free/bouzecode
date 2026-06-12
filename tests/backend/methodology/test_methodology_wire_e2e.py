# [desc] E2E wire-level tests verifying methodology cache_control breakpoints and context persistence across turns
# <tool_use name="FinalAnswer" id="r1"><param name="answer">E2E wire-level tests verifying methodology cache_control breakpoints and context persistence across turns</param></tool_use> [/desc]
"""The byte-level cache split/budget invariants live (fast) in methodology/cache/*; this
file proves the END RESULT on the real wire: the methodology system blocks carry
cache_control breakpoints and the cached methodology context is re-sent each turn —
asserted on result.recorded_requests (the real request bodies the pipeline produced).
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode


def _meth(content):
    return f'<tool_use name="Methodology" id="m1"><param name="content">{content}</param></tool_use>'


def _system_blocks(req):
    s = req.get("system")
    return s if isinstance(s, list) else [{"type": "text", "text": str(s)}]


def test_cache_control_breakpoint_reaches_the_wire():
    """At least one system block carries a cache_control breakpoint on the real request."""
    result = bouzecode(
        ["t1", "t2"],
        mock_api=[f"a.\n{_meth('durable project context to cache')}", f"b.\n{_meth('more')}"],
    )
    blocks = _system_blocks(result.recorded_requests[-1])
    assert any(isinstance(b, dict) and "cache_control" in b for b in blocks), \
        "a cache_control breakpoint should reach the wire system blocks"


def test_methodology_context_is_re_sent_on_every_turn():
    """The methodology note recorded on turn 1 is present in the wire system of later
    turns (the cached prefix is re-sent so the model keeps the context)."""
    result = bouzecode(
        ["t1", "t2", "t3"],
        mock_api=[f"a.\n{_meth('PIN_THIS_CONTEXT')}", f"b.\n{_meth('x')}", f"c.\n{_meth('y')}"],
    )
    last_system = str(result.recorded_requests[-1].get("system"))
    assert "PIN_THIS_CONTEXT" in last_system
