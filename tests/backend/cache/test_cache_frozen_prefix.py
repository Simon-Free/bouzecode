# [desc] Tests that cache-control anchors remain byte-stable across tool iterations and turn boundaries. [/desc]
"""Reproduces the cache-thrash bug. No real API calls.

Behavior under test: once the LLM hands back to the user, everything up to
that point is "frozen" — tool calls/results elided — and future API calls
read it from cache instead of rewriting 7-18K tokens.

Two failure modes:
  1. Intra-turn: `prepend_verbatim_audit` mutates the LAST neutral `user`
     msg every tool cycle. In a single-user-msg agentic loop that's the
     original msg, so its bytes drift between calls.
  2. Cross-turn: `messages_to_anthropic` anchors `cache_control` on the
     sliding last-2 window, never on the frozen turn boundary.
"""
from __future__ import annotations

from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.agent.minimal_payload import build_messages_for_api
from bouzecode.backend.agent.providers.conversion import messages_to_anthropic


class _FakeState:
    def __init__(self, messages, context_state=None):
        self.messages = messages
        self.context_state = context_state or ContextState()
        self.compaction_log = []
        self.turn_count = 1


def _api_payload(messages, context_state):
    state = _FakeState(list(messages), context_state=context_state)
    return messages_to_anthropic(build_messages_for_api(state, {}))


def _flatten(payload):
    out = []
    for msg in payload:
        content = msg.get("content")
        if isinstance(content, list):
            text = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content
            )
        else:
            text = content or ""
        out.append((msg.get("role"), text))
    return out


def _anchor_positions(payload):
    return [
        i for i, msg in enumerate(payload)
        if isinstance(msg.get("content"), list)
        and any(
            isinstance(b, dict) and b.get("cache_control")
            for b in msg["content"]
        )
    ]


def _find_msg_with(flat, needle):
    for i, (_, text) in enumerate(flat):
        if needle in text:
            return i
    return None


def _msgs_one_tool_result():
    return [
        {"role": "user", "content": "Enquête sur le cache."},
        {
            "role": "assistant",
            "content": '<tool_use name="Read" id="r1"><param name="file_path">foo.py</param></tool_use>',
            "tool_calls": [{"id": "r1", "name": "Read", "input": {"file_path": "foo.py"}}],
        },
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "FOO " * 400},
    ]


def _msgs_two_tool_results():
    msgs = _msgs_one_tool_result()
    msgs.append({
        "role": "assistant",
        "content": '<tool_use name="Bash" id="b1"><param name="command">ls</param></tool_use>',
        "tool_calls": [{"id": "b1", "name": "Bash", "input": {"command": "ls"}}],
    })
    msgs.append({"role": "tool", "tool_call_id": "b1", "name": "Bash", "content": "LS " * 50})
    return msgs


def _msgs_end_of_turn1():
    return [
        {"role": "user", "content": "read foo.py"},
        {
            "role": "assistant",
            "content": '<tool_use name="Read" id="r1"><param name="file_path">foo.py</param></tool_use>',
            "tool_calls": [{"id": "r1", "name": "Read", "input": {"file_path": "foo.py"}}],
        },
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "FOO " * 400},
        {"role": "assistant", "content": "foo is X", "tool_calls": []},
    ]


def test_notes_do_not_mutate_user_messages():
    """Working memory notes live in the system volatile block, not in the
    message list. Otherwise the same bug as the audit: notes grow each turn
    → last user msg bytes drift → Anthropic cache evicted."""
    gc = ContextState()
    gc.notes["methodology"] = "step 1: read\nstep 2: fix\nstep 3: test"
    gc.notes["progress"] = "r1 done, r2 pending"
    payload = _flatten(_api_payload(_msgs_one_tool_result(), gc))
    for role, text in payload:
        assert "Your working memory notes" not in text, (
            f"notes leaked into {role} msg: {text[:120]!r}"
        )
        assert "methodology" not in text or role == "assistant", (
            f"notes content leaked into {role} msg: {text[:120]!r}"
        )
