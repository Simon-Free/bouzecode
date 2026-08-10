"""Test that build_items_for_payload includes full 'text' field (not truncated).

Bug: all _*_item functions only produced a 'preview' field (truncated to 300-400 chars),
so the turn detail UI could never display the full model input/output.
"""
import pytest

from bouzecode.web_v2.runtime.context_viewer.items import build_items_for_payload


class FakeGcState:
    """Minimal context_state stub."""
    def __init__(self, notes=None):
        self.notes = notes or {}


LONG_SYSTEM = "S" * 5000  # 5000 chars, way over the 300-char preview limit
LONG_USER = "U" * 5000
LONG_TOOL_RESULT = "R" * 5000
LONG_ASSISTANT_TEXT = "A" * 5000


def _make_payload():
    """Build a minimal payload with long content in each role."""
    return [
        {"role": "user", "content": LONG_USER},
        {
            "role": "assistant",
            "content": LONG_ASSISTANT_TEXT,
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "Read",
                    "input": {"file_path": "/some/file.py"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "Read",
            "content": LONG_TOOL_RESULT,
        },
    ]


def test_items_have_full_text_field():
    """Each item must have a 'text' field containing the full (non-truncated) content."""
    payload = _make_payload()
    tc_index = {"call_1": ("Read", {"file_path": "/some/file.py"})}
    context_state = FakeGcState()

    items = build_items_for_payload(payload, LONG_SYSTEM, context_state, tc_index)

    # items[0] = system prompt
    system_item = items[0]
    assert system_item["kind"] == "system"
    assert "text" in system_item, "system item must have 'text' field"
    assert system_item["text"] == LONG_SYSTEM
    assert len(system_item["preview"]) < len(LONG_SYSTEM)  # preview IS truncated

    # items[1] = user message
    user_item = items[1]
    assert user_item["kind"] == "user"
    assert "text" in user_item, "user item must have 'text' field"
    assert user_item["text"] == LONG_USER
    assert len(user_item["preview"]) < len(LONG_USER)

    # items[2] = assistant message
    asst_item = items[2]
    assert asst_item["kind"] == "assistant"
    assert "text" in asst_item, "assistant item must have 'text' field"
    # assistant text includes serialized tool calls, so it should START with the long text
    assert asst_item["text"].startswith(LONG_ASSISTANT_TEXT)
    assert len(asst_item["text"]) >= len(LONG_ASSISTANT_TEXT)

    # items[3] = tool result
    tool_item = items[3]
    assert tool_item["kind"] == "tool_result"
    assert "text" in tool_item, "tool_result item must have 'text' field"
    assert tool_item["text"] == LONG_TOOL_RESULT
    assert len(tool_item["preview"]) < len(LONG_TOOL_RESULT)


def test_notes_item_has_full_text():
    """Notes item must also have full text."""
    payload = [{"role": "user", "content": "hello"}]
    notes = {"methodology": "M" * 3000}
    context_state = FakeGcState(notes=notes)

    items = build_items_for_payload(payload, "sys", context_state, {})

    notes_item = next((i for i in items if i["kind"] == "notes_block"), None)
    assert notes_item is not None, "notes_block item should exist"
    assert "text" in notes_item, "notes item must have 'text' field"
    assert "M" * 3000 in notes_item["text"]
    assert len(notes_item["preview"]) <= 400  # preview is truncated
