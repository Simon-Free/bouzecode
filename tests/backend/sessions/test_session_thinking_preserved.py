# [desc] Tests that thinking blocks are preserved (not stripped) when building session save data. [/desc]
"""Test that thinking blocks are preserved in saved session data."""
from unittest.mock import MagicMock

from bouzecode.backend.commands.session import _build_session_data


def test_thinking_blocks_preserved_in_session():
    """Thinking blocks in assistant messages must NOT be stripped when saving sessions.

    The HTML renderer needs them to display thinking content.
    """
    thinking_content = (
        "<thinking>\n"
        "  Let me analyze this problem step by step.\n"
        "  The user wants to fix a bug in the parser.\n"
        "</thinking>\n\n"
        "I found the issue in the parser module."
    )

    state = MagicMock()
    state.messages = [
        {"role": "user", "content": "Fix the parser bug"},
        {"role": "assistant", "content": thinking_content, "tool_calls": []},
    ]
    state.turn_count = 1
    state.user_loop_count = 0
    state.total_tool_calls = 0
    state.total_input_tokens = 100
    state.total_output_tokens = 200
    state.total_cache_read_tokens = 0
    state.total_cache_creation_tokens = 0
    state.compaction_log = []
    state.distinct_base = 0
    state.context_state = MagicMock()
    state.context_state.notes = ""
    state.notes_timeline = []
    state.thinking_log = []
    state.last_api_payload = []
    state.system_prompt = ""
    state.bouzecode_commit = ""
    state.bouzecode_version = ""

    data = _build_session_data(state, session_id="test123")

    assistant_msg = data["messages"][1]
    # Thinking block must be present in saved content
    assert "<thinking>" in assistant_msg["content"], (
        f"Thinking block was stripped! Content: {assistant_msg['content']!r}"
    )
    assert "analyze this problem" in assistant_msg["content"]
    # Prose after thinking must also be present
    assert "I found the issue" in assistant_msg["content"]


def test_thinking_only_message_not_dot():
    """A message with ONLY thinking content must NOT become '.' in saved session."""
    thinking_only = (
        "<thinking>\n"
        "  Planning my approach to this task.\n"
        "</thinking>"
    )

    state = MagicMock()
    state.messages = [
        {"role": "user", "content": "Help me"},
        {"role": "assistant", "content": thinking_only, "tool_calls": []},
    ]
    state.turn_count = 1
    state.user_loop_count = 0
    state.total_tool_calls = 0
    state.total_input_tokens = 100
    state.total_output_tokens = 200
    state.total_cache_read_tokens = 0
    state.total_cache_creation_tokens = 0
    state.compaction_log = []
    state.distinct_base = 0
    state.context_state = MagicMock()
    state.context_state.notes = ""
    state.notes_timeline = []
    state.thinking_log = []
    state.last_api_payload = []
    state.system_prompt = ""
    state.bouzecode_commit = ""
    state.bouzecode_version = ""

    data = _build_session_data(state, session_id="test456")

    assistant_msg = data["messages"][1]
    assert assistant_msg["content"] != ".", (
        "Thinking-only message was reduced to '.' — thinking blocks must be preserved"
    )
    assert "<thinking>" in assistant_msg["content"]
