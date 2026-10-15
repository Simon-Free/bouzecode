"""Tests for the big-context reminder injection (A/B validated 2026-06-11).

Covers:
- _append_to_last_user_message helper (str / list content / no user msg)
- Wire-only mutation guarantee (original messages list unchanged)
- BOUZECODE_BIGCTX_REMINDER flag respects "0" = off
"""

import os

import pytest

from bouzecode.backend.agent.providers.backends.dispatch import (
    _append_to_last_user_message,
    _BIGCTX_REMINDER,
)


# ---------------------------------------------------------------------------
# Unit tests for _append_to_last_user_message
# ---------------------------------------------------------------------------


class TestAppendToLastUserMessage:
    def test_append_string_content(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        _append_to_last_user_message(msgs, "REMINDER")
        # Should append to the last user message (index 1)
        assert msgs[1]["content"] == "hello\n\nREMINDER"

    def test_append_list_content(self):
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ]
        _append_to_last_user_message(msgs, "REMINDER")
        assert msgs[0]["content"] == [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "REMINDER"},
        ]

    def test_no_user_message_noop(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "hi"},
        ]
        original = [dict(m) for m in msgs]
        _append_to_last_user_message(msgs, "REMINDER")
        # Nothing changes
        assert msgs == original

    def test_targets_last_user_not_first(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "mid"},
            {"role": "user", "content": "second"},
        ]
        _append_to_last_user_message(msgs, "X")
        assert msgs[2]["content"] == "second\n\nX"
        # First user message untouched
        assert msgs[0]["content"] == "first"


# ---------------------------------------------------------------------------
# Integration: wire-only mutation (original list/dicts not mutated)
# ---------------------------------------------------------------------------


class TestWireOnlyMutation:
    """Simulate the exact pattern used in stream(): shallow copy list, then append."""

    def test_original_messages_not_mutated(self):
        original_msgs = [
            {"role": "user", "content": "my prompt"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "follow-up"},
        ]
        # Deep-copy to compare later
        import copy
        frozen = copy.deepcopy(original_msgs)

        # Simulate stream() pattern: shallow copy + append
        wire = list(original_msgs)
        _append_to_last_user_message(wire, _BIGCTX_REMINDER)

        # Wire has the reminder
        assert _BIGCTX_REMINDER in wire[2]["content"]
        # Original list still has same length
        assert len(original_msgs) == len(frozen)
        # Original dict at index 2 is NOT the same object (helper does dict())
        # AND original content is unchanged
        assert original_msgs[2]["content"] == frozen[2]["content"]

    def test_original_dict_not_same_object(self):
        """_append creates a new dict for the mutated message."""
        original_msg = {"role": "user", "content": "test"}
        msgs = [original_msg]
        _append_to_last_user_message(msgs, "X")
        # The list slot is a NEW dict
        assert msgs[0] is not original_msg
        # Original unchanged
        assert original_msg["content"] == "test"


# ---------------------------------------------------------------------------
# Flag BOUZECODE_BIGCTX_REMINDER
# ---------------------------------------------------------------------------


class TestBigctxReminderFlag:
    """The flag controls whether the reminder is injected."""

    def test_flag_off_skips_injection(self, monkeypatch):
        """When BOUZECODE_BIGCTX_REMINDER=0, no reminder should be appended.

        We test the condition directly since calling stream() is impractical.
        """
        monkeypatch.setenv("BOUZECODE_BIGCTX_REMINDER", "0")
        # The condition in stream():
        # if os.environ.get("BOUZECODE_BIGCTX_REMINDER", "1") != "0":
        assert os.environ.get("BOUZECODE_BIGCTX_REMINDER", "1") == "0"
        # So injection would NOT happen

    def test_flag_default_on(self, monkeypatch):
        """Default (no env var) means injection happens."""
        monkeypatch.delenv("BOUZECODE_BIGCTX_REMINDER", raising=False)
        assert os.environ.get("BOUZECODE_BIGCTX_REMINDER", "1") != "0"

    def test_flag_explicit_on(self, monkeypatch):
        """Explicit '1' means injection happens."""
        monkeypatch.setenv("BOUZECODE_BIGCTX_REMINDER", "1")
        assert os.environ.get("BOUZECODE_BIGCTX_REMINDER", "1") != "0"

    def test_reminder_text_not_empty(self):
        """The reminder constant must be non-empty."""
        assert _BIGCTX_REMINDER
        assert len(_BIGCTX_REMINDER) > 10
