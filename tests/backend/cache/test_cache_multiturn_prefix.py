# [desc] Tests that Anthropic API payloads share byte-stable prefixes within and across agent loop turns. [/desc]
"""Simulates a realistic multi-turn agentic conversation (user → assistant →
tool_call → tool_result → assistant → user → …) and checks that the Anthropic
API payloads share a byte-stable prefix within the same user turn, and that
the compacted form is stable across turns.

No API key required — we build the exact same payloads dispatch.py would build,
then compare them structurally.

Covers both bugs:
  - Bug 1 (audit): prepend_verbatim_audit used to mutate the last user msg
  - Bug 2 (notes): inject_notes used to mutate the last user msg
Both are now injected into the volatile system block, leaving messages intact.
"""
from __future__ import annotations

from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.agent.minimal_payload import build_messages_for_api
from bouzecode.backend.agent.providers.conversion import messages_to_anthropic


class _FakeState:
    def __init__(self, messages, context_state=None):
        self.messages = list(messages)
        self.context_state = context_state or ContextState()
        self.compaction_log = []
        self.turn_count = len([m for m in messages if m.get("role") == "user"])


def _api_payload(messages, context_state=None):
    state = _FakeState(messages, context_state=context_state)
    return messages_to_anthropic(build_messages_for_api(state, {}))


def _flatten_text(payload):
    """Extract (role, text) pairs from an anthropic-formatted payload."""
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
        out.append((msg["role"], text))
    return out


def _assert_prefix_stable(payloads, label=""):
    """Check that each payload's prefix is byte-identical to the previous."""
    for i in range(1, len(payloads)):
        prev, curr = payloads[i - 1], payloads[i]
        # Last 2 messages get cache_control rewritten each time,
        # so we only check messages before the shorter payload's last 2.
        check_up_to = max(0, len(prev) - 2)
        for j in range(check_up_to):
            assert prev[j] == curr[j], (
                f"{label}Call {i} vs call {i+1}: prefix drifted at msg {j}.\n"
                f"  prev[{j}] = {prev[j][0]}: {prev[j][1][:100]!r}\n"
                f"  curr[{j}] = {curr[j][0]}: {curr[j][1][:100]!r}"
            )


# -- Conversation builders ---------------------------------------------------

def _build_intra_turn_calls():
    """3 API calls within the same user turn (agentic tool loop).

    Call 1: user message → LLM
    Call 2: assistant+tool_result → LLM (second tool call)
    Call 3: assistant+tool_result → LLM (third tool call)
    """
    call1 = [
        {"role": "user", "content": "Analyse le fichier config.py"},
    ]

    call2 = call1 + [
        {
            "role": "assistant",
            "content": 'Let me read that file.\n<tool_use name="Read" id="r1"><param name="file_path">config.py</param></tool_use>',
            "tool_calls": [{"id": "r1", "name": "Read", "input": {"file_path": "config.py"}}],
        },
        {"role": "tool", "tool_call_id": "r1", "name": "Read",
         "content": "# config.py\nDEBUG = True\nPORT = 8080\n" + "# filler\n" * 200},
    ]

    call3 = call2 + [
        {
            "role": "assistant",
            "content": 'Now checking the main file.\n<tool_use name="Read" id="r2"><param name="file_path">main.py</param></tool_use>',
            "tool_calls": [{"id": "r2", "name": "Read", "input": {"file_path": "main.py"}}],
        },
        {"role": "tool", "tool_call_id": "r2", "name": "Read",
         "content": "# main.py\nimport config\napp = Flask(__name__)\n" + "# filler\n" * 200},
    ]

    return [list(c) for c in [call1, call2, call3]]


def _build_cross_turn_calls():
    """2 API calls in user turn 2, after turn 1 completed.

    Compaction already applied (turn 1 assistant XML compacted).
    Both calls share the same compacted prefix.
    """
    # Complete turn 1
    turn1_done = [
        {"role": "user", "content": "Analyse le fichier config.py"},
        {
            "role": "assistant",
            "content": 'Let me read that file.\n<tool_use name="Read" id="r1"><param name="file_path">config.py</param></tool_use>',
            "tool_calls": [{"id": "r1", "name": "Read", "input": {"file_path": "config.py"}}],
        },
        {"role": "tool", "tool_call_id": "r1", "name": "Read",
         "content": "# config.py\nDEBUG = True\nPORT = 8080\n" + "# filler\n" * 200},
        {"role": "assistant", "content": "config.py has DEBUG=True and PORT=8080.", "tool_calls": []},
    ]

    # Turn 2, call 1: new user question
    t2_call1 = turn1_done + [
        {"role": "user", "content": "Change le port à 9090"},
    ]

    # Turn 2, call 2: assistant used a tool, tool_result back
    t2_call2 = t2_call1 + [
        {
            "role": "assistant",
            "content": 'Editing config.\n<tool_use name="Edit" id="e1"><param name="file_path">config.py</param></tool_use>',
            "tool_calls": [{"id": "e1", "name": "Edit", "input": {"file_path": "config.py"}}],
        },
        {"role": "tool", "tool_call_id": "e1", "name": "Edit",
         "content": "OK, edited config.py"},
    ]

    return [list(c) for c in [t2_call1, t2_call2]]


# -- Tests -------------------------------------------------------------------

def test_intra_turn_prefix_stable():
    """Within the same user turn (agentic tool loop): prefix must be byte-stable."""
    calls = _build_intra_turn_calls()
    payloads = [_flatten_text(_api_payload(msgs)) for msgs in calls]
    _assert_prefix_stable(payloads, label="Intra-turn: ")


def test_cross_turn_prefix_stable():
    """After a turn boundary (compaction applied): the compacted prefix must
    be stable for subsequent calls in the new turn."""
    calls = _build_cross_turn_calls()
    payloads = [_flatten_text(_api_payload(msgs)) for msgs in calls]
    _assert_prefix_stable(payloads, label="Cross-turn: ")


def test_intra_turn_stable_with_growing_notes():
    """Notes growing each tool cycle must NOT affect message prefix."""
    calls = _build_intra_turn_calls()
    gc = ContextState()
    gc.notes["methodology"] = "1. read config 2. read main 3. propose change"

    payloads = []
    for i, msgs in enumerate(calls):
        payloads.append(_flatten_text(_api_payload(msgs, gc)))
        if i == 0:
            gc.notes["progress"] = "config.py analyzed"
        elif i == 1:
            gc.notes["progress"] = "config.py + main.py analyzed"
            gc.notes["files_seen"] = "config.py, main.py"

    _assert_prefix_stable(payloads, label="Notes intra-turn: ")

    # Notes must never appear in any message text
    for call_idx, payload in enumerate(payloads):
        for msg_idx, (role, text) in enumerate(payload):
            assert "working memory notes" not in text.lower(), (
                f"Notes leaked into call {call_idx+1} msg {msg_idx} ({role}): "
                f"{text[:120]!r}"
            )
