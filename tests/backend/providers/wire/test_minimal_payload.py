# [desc] Tests for minimal_payload.py — thinking stripping, tool compaction, and wire payload building
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests for minimal_payload.py — thinking stripping, tool compaction, and wire payload building</param></tool_use> [/desc]
"""Tests for minimal_payload.py — the methodology-centric wire pipeline."""
from __future__ import annotations

from bouzecode.backend.agent.minimal_payload import (
    build_messages_for_api,
    build_minimal_payload,
    _strip_thinking_blocks,
    _strip_thinking_from_messages,
)


HEAVY = "X" * 5000


class _FakeState:
    def __init__(self, messages):
        self.messages = messages
        self.compaction_log = []
        self.turn_count = 1


class TestBuildMessagesForApi:
    def test_mid_loop_compacts_prior_turns_keeps_current(self):
        """Mid-loop (last msg is tool): prior turn gets compacted, current turn intact."""
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "follow"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t2", "name": "Read", "input": {"file_path": "b.py"}}]},
            {"role": "tool", "tool_call_id": "t2", "name": "Read", "content": HEAVY},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1, "t1 (prior turn) must be compacted, t2 (current turn) kept"
        assert HEAVY in tool_msgs[0]["content"]
        assert tool_msgs[0]["tool_call_id"] == "t2"

    def test_user_turn_compacts_prior_tools(self):
        """When last message is user (new turn), prior tool content is removed."""
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "follow"},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 0

    def test_no_user_msg_on_wire_with_live_batch(self):
        """With a live batch, user msg is not on wire (methodology-centric)."""
        history = [
            {"role": "user", "content": "do stuff"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "b99", "name": "Bash", "input": {"command": "ls"}}
            ]},
            {"role": "tool", "tool_call_id": "b99", "name": "Bash", "content": "output"},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        user_msgs = [m for m in result if m.get("role") == "user"]
        assert not user_msgs, "User msg should not be on wire when live batch exists"

    def test_strips_thinking_before_pruning(self):
        """Thinking blocks are stripped before minimal payload pruning."""
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "<thinking>\nreasoning\n</thinking>\nanswer", "tool_calls": [
                {"id": "r1", "name": "Read", "input": {"file_path": "x.py"}}
            ]},
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "data"},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        for msg in result:
            content = msg.get("content", "")
            if isinstance(content, str):
                assert "<thinking>" not in content


class TestStripThinkingBlocks:
    def test_standard_block(self):
        text = "<thinking>\nreasoning here\n</thinking>\nanswer"
        assert _strip_thinking_blocks(text) == "answer"

    def test_unclosed_block(self):
        text = "<thinking>\nreasoning that got interrupted"
        assert _strip_thinking_blocks(text) == ""

    def test_multiple_blocks(self):
        text = "<thinking>\nA\n</thinking>\nX\n<thinking>\nB\n</thinking>\nY"
        result = _strip_thinking_blocks(text)
        assert "X" in result
        assert "Y" in result
        assert "A" not in result
        assert "B" not in result

    def test_no_thinking(self):
        assert _strip_thinking_blocks("just text") == "just text"

    def test_preserves_text_before_thinking(self):
        text = "before\n<thinking>\nreasoning\n</thinking>\nafter"
        result = _strip_thinking_blocks(text)
        assert "before" in result
        assert "after" in result
        assert "reasoning" not in result


class TestStripThinkingFromMessages:
    def test_strip_assistant(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "<thinking>\nr\n</thinking>\nanswer"},
        ]
        result = _strip_thinking_from_messages(msgs)
        assert result[0]["content"] == "hi"
        assert "answer" in result[1]["content"]
        assert "<thinking>" not in result[1]["content"]

    def test_user_unchanged(self):
        msgs = [{"role": "user", "content": "about thinking tags"}]
        result = _strip_thinking_from_messages(msgs)
        assert result[0]["content"] == "about thinking tags"

    def test_empty_after_strip_uses_placeholder(self):
        msgs = [{"role": "assistant", "content": "<thinking>\nonly thinking\n</thinking>"}]
        result = _strip_thinking_from_messages(msgs)
        assert result[0]["content"] == "."

    def test_list_content_blocks(self):
        msgs = [{"role": "assistant", "content": [
            {"type": "text", "text": "<thinking>\nreasoning\n</thinking>\nanswer"},
        ]}]
        result = _strip_thinking_from_messages(msgs)
        block = result[0]["content"][0]
        assert "answer" in block["text"]
        assert "reasoning" not in block["text"]
