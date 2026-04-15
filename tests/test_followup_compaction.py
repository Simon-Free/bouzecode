# [desc] Unit tests for follow-up compaction: stubbing past-turn tool_results while preserving current turn and exempt tools. [/desc]
"""Tests for followup_compaction.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from followup_compaction import (
    compact_tool_history,
    build_messages_for_api,
    DEFAULT_EXEMPT_TOOLS,
)


def _turn(user_text: str, tool_calls: list, tool_results: list) -> list:
    """Build [user, assistant+tool_calls, tool_result, tool_result, ...]."""
    msgs = [{"role": "user", "content": user_text}]
    msgs.append({"role": "assistant", "content": "ok", "tool_calls": tool_calls})
    msgs.extend(tool_results)
    return msgs


HEAVY = "X" * 5000


class TestCompactToolHistory:
    def test_stubs_old_tool_results(self):
        history = (
            _turn(
                "first question",
                [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + [{"role": "assistant", "content": "done", "tool_calls": []}]
            + _turn(
                "follow up",
                [{"id": "t2", "name": "Read", "input": {"file_path": "b.py"}}],
                [{"role": "tool", "tool_call_id": "t2", "name": "Read", "content": HEAVY}],
            )
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        # Old tool result stubbed
        assert "Read" in out[2]["content"]
        assert "elided" in out[2]["content"]
        assert HEAVY not in out[2]["content"]

    def test_current_turn_intact(self):
        history = (
            _turn(
                "first",
                [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + _turn(
                "current",
                [{"id": "t2", "name": "Bash", "input": {"command": "ls"}}],
                [{"role": "tool", "tool_call_id": "t2", "name": "Bash", "content": HEAVY}],
            )
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        # Last turn's tool result must remain verbatim
        assert out[-1]["content"] == HEAVY

    def test_keep_last_n_turns_1(self):
        history = (
            _turn(
                "first",
                [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + _turn(
                "second",
                [{"id": "t2", "name": "Read", "input": {"file_path": "b.py"}}],
                [{"role": "tool", "tool_call_id": "t2", "name": "Read", "content": HEAVY}],
            )
            + _turn(
                "third (current)",
                [{"id": "t3", "name": "Read", "input": {"file_path": "c.py"}}],
                [{"role": "tool", "tool_call_id": "t3", "name": "Read", "content": HEAVY}],
            )
        )
        out = compact_tool_history(history, keep_last_n_turns=1)
        # Find each tool message by id
        by_id = {m["tool_call_id"]: m for m in out if m.get("role") == "tool"}
        assert HEAVY not in by_id["t1"]["content"]
        assert by_id["t2"]["content"] == HEAVY
        assert by_id["t3"]["content"] == HEAVY

    def test_exempt_tools_preserved(self):
        history = (
            _turn(
                "first",
                [
                    {"id": "ed1", "name": "Edit", "input": {"file_path": "a.py", "old_string": "x", "new_string": "y"}},
                    {"id": "rd1", "name": "Read", "input": {"file_path": "z.py"}},
                ],
                [
                    {"role": "tool", "tool_call_id": "ed1", "name": "Edit", "content": "Edited successfully"},
                    {"role": "tool", "tool_call_id": "rd1", "name": "Read", "content": HEAVY},
                ],
            )
            + [{"role": "user", "content": "next"}]
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        by_id = {m["tool_call_id"]: m for m in out if m.get("role") == "tool"}
        assert by_id["ed1"]["content"] == "Edited successfully"
        assert HEAVY not in by_id["rd1"]["content"]

    def test_non_destructive(self):
        original = _turn(
            "q",
            [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
            [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
        ) + [{"role": "user", "content": "follow"}]
        snapshot_content = original[2]["content"]
        compact_tool_history(original, keep_last_n_turns=0)
        assert original[2]["content"] == snapshot_content
        assert original[2]["content"] == HEAVY

    def test_stub_format_read(self):
        history = (
            _turn(
                "q",
                [{"id": "t1", "name": "Read", "input": {"file_path": "/p/a.py", "offset": 10, "limit": 50}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + [{"role": "user", "content": "follow"}]
        )
        out = compact_tool_history(history)
        stub = out[2]["content"]
        assert "Read(" in stub
        assert "file_path=/p/a.py" in stub
        assert "offset=10" in stub
        assert "limit=50" in stub

    def test_stub_format_bash(self):
        long_cmd = "echo " + "a" * 200
        history = (
            _turn(
                "q",
                [{"id": "t1", "name": "Bash", "input": {"command": long_cmd}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Bash", "content": HEAVY}],
            )
            + [{"role": "user", "content": "follow"}]
        )
        out = compact_tool_history(history)
        stub = out[2]["content"]
        assert "Bash(" in stub
        assert "..." in stub  # truncated

    def test_stub_format_grep(self):
        history = (
            _turn(
                "q",
                [{"id": "t1", "name": "Grep", "input": {"pattern": "TODO", "path": "src/"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Grep", "content": HEAVY}],
            )
            + [{"role": "user", "content": "follow"}]
        )
        out = compact_tool_history(history)
        stub = out[2]["content"]
        assert "Grep(" in stub
        assert "pattern='TODO'" in stub
        assert "path=src/" in stub

    def test_unmatched_tool_call_id_falls_back_safely(self):
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "ok", "tool_calls": []},
            {"role": "tool", "tool_call_id": "ghost", "name": "Mystery", "content": HEAVY},
            {"role": "user", "content": "follow"},
        ]
        out = compact_tool_history(history)
        stub = out[2]["content"]
        assert "Mystery(" in stub
        assert HEAVY not in stub

    def test_no_compaction_when_only_one_turn(self):
        history = _turn(
            "only",
            [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
            [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        assert out[2]["content"] == HEAVY


class _FakeState:
    def __init__(self, messages):
        self.messages = messages
        self.compaction_log = []
        self.turn_count = 1


class TestBuildMessagesForApi:
    def test_disabled_returns_state_messages_unchanged(self):
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "user", "content": "follow"},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {"followup_compaction_enabled": False})
        assert result == state.messages
        assert state.compaction_log == []

    def test_enabled_logs_savings(self):
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "user", "content": "follow"},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        assert HEAVY not in result[2]["content"]
        assert any(e["event"] == "followup_compact" for e in state.compaction_log)
        entry = state.compaction_log[-1]
        assert entry["tokens_est_saved"] > 0
        assert entry["tokens_est_before"] > entry["tokens_est_after"]

    def test_default_exempt_includes_edit_write_todowrite(self):
        assert "Edit" in DEFAULT_EXEMPT_TOOLS
        assert "Write" in DEFAULT_EXEMPT_TOOLS
        assert "TodoWrite" in DEFAULT_EXEMPT_TOOLS
