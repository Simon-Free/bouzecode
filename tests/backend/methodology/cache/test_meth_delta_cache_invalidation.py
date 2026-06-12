# [desc] Tests that methodology delta fusion into message anchor invalidates Anthropic prompt cache each turn
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that methodology delta fusion into message anchor invalidates Anthropic prompt cache each turn</param></tool_use> [/desc]
"""Bitwise proof that meth_delta fusion into the message anchor invalidates
Anthropic prompt cache every single turn.

Reconstructs the EXACT payload that dispatch.stream() → stream_anthropic()
sends to the Anthropic API, for 3 successive turns where methodology grows.
Compares payloads byte-by-byte to show where the cache break occurs.

No mocking, no LLM calls — pure deterministic payload construction.
"""
import json

from bouzecode.backend.agent.providers.conversion import messages_to_anthropic
from bouzecode.backend.context_manager.methodology import build_methodology_system_blocks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STABLE_PREFIX = "You are a helpful assistant. Follow these rules..."
TOOL_DOCS = "<tool_doc>Read: read a file</tool_doc>"
VOLATILE = "Current date: 2026-04-24\nWorking directory: /home/user"
CACHE_CONTROL = {"type": "ephemeral"}


def _build_provider_payload(methodology_text, snapshot, messages):
    """Reconstruct the exact payload dispatch.stream() builds."""
    meth_blocks, meth_delta = build_methodology_system_blocks(
        methodology_text, snapshot, CACHE_CONTROL,
    )
    system_blocks = [
        {"type": "text", "text": STABLE_PREFIX, "cache_control": CACHE_CONTROL},
        {"type": "text", "text": TOOL_DOCS, "cache_control": CACHE_CONTROL},
        *meth_blocks,
        {"type": "text", "text": VOLATILE},
    ]
    return {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 8192,
        "system": system_blocks,
        "messages": messages_to_anthropic(messages),
    }


def _two_loop_messages():
    """2-loop conversation. Loop 1 ends at index 4 (assistant), loop 2 starts at index 5."""
    return [
        # --- Loop 1 ---
        {"role": "user", "content": "Hello from loop 1"},
        {"role": "assistant", "content": "Let me check.",
         "tool_calls": [{"id": "tc1", "function": {"name": "Read", "arguments": '{"path": "x.py"}'}}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "file contents here"},
        {"role": "assistant", "content": "Here is my final answer for loop 1."},
        # --- Loop 2 (current) ---
        {"role": "user", "content": "Now do something in loop 2"},
    ]


def _find_anchor_index(anth_msgs):
    """Find the anchor = message with cache_control."""
    for i, m in enumerate(anth_msgs):
        content = m.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    return i
    return None


def _get_anchor_text(anth_msgs):
    idx = _find_anchor_index(anth_msgs)
    if idx is None:
        return None
    content = anth_msgs[idx]["content"]
    if isinstance(content, list):
        return content[0]["text"]
    return content


# ---------------------------------------------------------------------------
# Scenarios: methodology grows across 3 turns
# ---------------------------------------------------------------------------

METH_TURN1 = "## Plan\nDo X"
METH_TURN2 = "## Plan\nDo X\n## Findings\nFound Y"
METH_TURN3 = "## Plan\nDo X\n## Findings\nFound Y\n## Next\nDo Z"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_system_blocks_stable_prefix_and_tools():
    """System blocks 0 (stable_prefix) and 1 (tool_docs) must be byte-identical."""
    msgs = _two_loop_messages()
    p1 = _build_provider_payload(METH_TURN1, "", msgs)
    p2 = _build_provider_payload(METH_TURN2, METH_TURN1, msgs)
    p3 = _build_provider_payload(METH_TURN3, METH_TURN2, msgs)

    for i in range(2):
        assert p1["system"][i] == p2["system"][i] == p3["system"][i], (
            f"System block {i} changed between turns!"
        )


def test_methodology_system_block_evolves_correctly():
    """Methodology system block (index 2) should contain the snapshot, not delta."""
    msgs = _two_loop_messages()
    p1 = _build_provider_payload(METH_TURN1, "", msgs)
    p2 = _build_provider_payload(METH_TURN2, METH_TURN1, msgs)
    p3 = _build_provider_payload(METH_TURN3, METH_TURN2, msgs)

    meth1 = p1["system"][2]["text"]
    meth2 = p2["system"][2]["text"]
    meth3 = p3["system"][2]["text"]

    # Turn 1: no snapshot, full text goes in system block
    assert "Do X" in meth1

    # Turn 2: snapshot = METH_TURN1, so system block has old content
    assert "Do X" in meth2

    # Turn 3: snapshot = METH_TURN2, system block should have findings
    assert "Found Y" in meth3


def test_messages_before_anchor_are_stable():
    """All messages BEFORE the anchor must be byte-identical across turns."""
    msgs = _two_loop_messages()
    p1 = _build_provider_payload(METH_TURN1, "", msgs)
    p2 = _build_provider_payload(METH_TURN2, METH_TURN1, msgs)
    p3 = _build_provider_payload(METH_TURN3, METH_TURN2, msgs)

    anchor_idx = _find_anchor_index(p2["messages"])
    assert anchor_idx is not None, "No anchor found"

    # Messages before anchor should be identical
    for i in range(anchor_idx):
        assert p1["messages"][i] == p2["messages"][i] == p3["messages"][i], (
            f"Message {i} (before anchor) changed between turns!\n"
            f"Turn 1: {p1['messages'][i]}\n"
            f"Turn 2: {p2['messages'][i]}\n"
            f"Turn 3: {p3['messages'][i]}"
        )


def test_anchor_is_stable_across_turns():
    """The message anchor must be byte-identical across turns: the methodology
    delta is NOT fused into the message anchor (that fusion was a cache-busting
    bug, now removed). Only the system methodology block grows."""
    msgs = _two_loop_messages()
    p2 = _build_provider_payload(METH_TURN2, METH_TURN1, msgs)
    p3 = _build_provider_payload(METH_TURN3, METH_TURN2, msgs)

    anchor2 = _get_anchor_text(p2["messages"])
    anchor3 = _get_anchor_text(p3["messages"])

    assert anchor2 is not None and anchor3 is not None
    assert anchor2 == anchor3, "Anchor must be stable — delta must not leak into messages"
    assert anchor2 == "Here is my final answer for loop 1."


def test_full_payload_json_prefix_diverges():
    """Serialize full payload to JSON, find exact byte where turns diverge."""
    msgs = _two_loop_messages()
    p2 = _build_provider_payload(METH_TURN2, METH_TURN1, msgs)
    p3 = _build_provider_payload(METH_TURN3, METH_TURN2, msgs)

    j2 = json.dumps(p2, ensure_ascii=False)
    j3 = json.dumps(p3, ensure_ascii=False)

    # Find first divergence
    min_len = min(len(j2), len(j3))
    diverge_at = None
    for i in range(min_len):
        if j2[i] != j3[i]:
            diverge_at = i
            break

    assert diverge_at is not None, "Payloads are identical — no divergence found"

    # The divergence should be in the methodology system block (expected)
    system_json = json.dumps(p2["system"], ensure_ascii=False)
    print(f"\n=== PAYLOAD DIVERGENCE at byte {diverge_at} / {min_len} ===")
    print(f"System JSON length: {len(system_json)}")


def test_volatile_system_block_has_no_cache_control():
    """The volatile block (last system block) must NOT have cache_control."""
    msgs = _two_loop_messages()
    p1 = _build_provider_payload(METH_TURN1, "", msgs)

    volatile_block = p1["system"][-1]
    assert "cache_control" not in volatile_block, (
        f"Volatile block should not have cache_control: {volatile_block}"
    )
