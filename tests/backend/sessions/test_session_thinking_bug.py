# [desc] Tests that thinking blocks are preserved (not stripped) in saved session JSON for HTML rendering [/desc]
"""Test that thinking blocks are preserved in session JSON for rendering."""
import uuid
from unittest.mock import patch

from bouzecode.backend.commands.session import _build_session_data


class FakeState:
    """Minimal state mock for _build_session_data."""
    def __init__(self, messages):
        self.messages = messages
        self.timing_entries = []
        self.compaction_log = []
        self.thinking_log = []
        self.turn_count = 1
        self.user_loop_count = 0
        self.total_tool_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0
        self.distinct_base = 0
        self.last_api_payload = []
        self.system_prompt = ""
        self.bouzecode_commit = ""
        self.bouzecode_version = ""
        self.notes_timeline = []

        from bouzecode.backend.context_manager import ContextState
        self.context_state = ContextState()


def test_thinking_preserved_in_session_json():
    """Bug repro: thinking blocks should NOT be stripped from saved session JSON.

    Currently _clean_message() calls strip_thinking_tags() which removes all
    <thinking>...</thinking> content. When a message is thinking-only, it becomes ".".
    The renderer then shows "." instead of the thinking content.
    """
    thinking_content = "<thinking>\nAnalysing the problem...\nThis is complex.\n</thinking>\n\nHere is my answer."
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": thinking_content, "tool_calls": []},
    ]
    state = FakeState(messages)

    with patch("bouzecode.backend.tools.state.get_file_snapshots", return_value={}):
        data = _build_session_data(state, session_id="test123")

    saved_messages = data["messages"]
    assistant_msg = next(m for m in saved_messages if m["role"] == "assistant")

    # The thinking block MUST be preserved for the renderer to display it
    assert "<thinking>" in assistant_msg["content"], (
        f"Thinking block was stripped! Got: {assistant_msg['content']!r}"
    )
    assert "Analysing the problem" in assistant_msg["content"]


def test_thinking_only_message_not_replaced_by_dot():
    """Bug repro: a thinking-only message should NOT become '.' in session JSON."""
    thinking_only = "<thinking>\nJust thinking here, no output text.\n</thinking>"
    messages = [
        {"role": "user", "content": "Think about this"},
        {"role": "assistant", "content": thinking_only, "tool_calls": []},
    ]
    state = FakeState(messages)

    with patch("bouzecode.backend.tools.state.get_file_snapshots", return_value={}):
        data = _build_session_data(state, session_id="test456")

    saved_messages = data["messages"]
    assistant_msg = next(m for m in saved_messages if m["role"] == "assistant")

    # Must NOT be replaced by "."
    assert assistant_msg["content"] != ".", (
        "Thinking-only message was replaced by '.' — this is the bug!"
    )
    assert "<thinking>" in assistant_msg["content"]
