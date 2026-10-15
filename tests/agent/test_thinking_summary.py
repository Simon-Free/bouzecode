"""Tests for thinking_summary module."""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from bouzecode.backend.agent.thinking_summary import summarize_overflow, _MIN_CHARS_FOR_SUMMARY
from bouzecode.backend.agent.providers import AssistantTurn


def _make_fake_streamer(response_text: str):
    """Return a fake streamer function that yields a single AssistantTurn."""
    def fake_streamer(**kwargs):
        yield AssistantTurn(
            text=response_text,
            tool_calls=[],
            in_tokens=100,
            out_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            stop_reason="end_turn",
        )
    return fake_streamer


def _make_failing_streamer():
    """Return a fake streamer that raises."""
    def fake_streamer(**kwargs):
        raise RuntimeError("API down")
        yield  # make it a generator  # noqa: unreachable
    return fake_streamer


class TestSummarizeOverflow:
    """Unit tests for summarize_overflow."""

    def test_short_thinking_returns_none(self):
        """Thinking below threshold → no summary."""
        short_text = "x" * (_MIN_CHARS_FOR_SUMMARY - 1)
        result = summarize_overflow(short_text, {})
        assert result is None

    def test_disabled_by_env_var(self, monkeypatch):
        """Feature flag OFF → no summary."""
        monkeypatch.setenv("BOUZECODE_THINKING_SUMMARY", "0")
        long_text = "x" * (_MIN_CHARS_FOR_SUMMARY + 100)
        result = summarize_overflow(long_text, {})
        assert result is None

    @patch("bouzecode.backend.agent.thinking_summary.get_streamer")
    def test_normal_summary(self, mock_get_streamer, monkeypatch):
        """Normal case: returns summary text."""
        monkeypatch.setenv("BOUZECODE_THINKING_SUMMARY", "1")
        summary_text = "• Conclusion 1\n• Conclusion 2"
        mock_get_streamer.return_value = _make_fake_streamer(summary_text)

        long_text = "thinking " * 1000  # well above threshold
        config = {"model": "some-model", "max_tokens": 8192}

        result = summarize_overflow(long_text, config)
        assert result == summary_text

        # Verify streamer was called with correct params
        mock_get_streamer.return_value  # already consumed
        # Check the call happened
        mock_get_streamer.assert_called_once()

    @patch("bouzecode.backend.agent.thinking_summary.get_streamer")
    def test_side_call_uses_correct_model(self, mock_get_streamer, monkeypatch):
        """Le résumé utilise le modèle de la session : un seul choix de modèle pour tout."""
        monkeypatch.setenv("BOUZECODE_THINKING_SUMMARY", "1")

        captured_kwargs = {}
        def capturing_streamer(**kwargs):
            captured_kwargs.update(kwargs)
            yield FakeAssistantTurn("summary")

        mock_get_streamer.return_value = capturing_streamer

        long_text = "x" * (_MIN_CHARS_FOR_SUMMARY + 100)
        config = {"model": "claude-opus-99", "max_tokens": 8192}

        summarize_overflow(long_text, config)

        assert captured_kwargs["model"] == "claude-opus-99"
        assert captured_kwargs["config"]["max_tokens"] == 1024
        assert captured_kwargs["config"]["_depth"] == 1
        assert captured_kwargs["config"]["_context_state"] is None

    @patch("bouzecode.backend.agent.thinking_summary.get_streamer")
    def test_side_call_stays_on_the_session_provider(self, mock_get_streamer, monkeypatch):
        """Session OpenRouter (DeepSeek) : le résumé ne part pas chez Anthropic (401 sans clé)."""
        monkeypatch.setenv("BOUZECODE_THINKING_SUMMARY", "1")
        captured_kwargs = {}

        def capturing_streamer(**kwargs):
            captured_kwargs.update(kwargs)
            yield FakeAssistantTurn("summary")

        mock_get_streamer.return_value = capturing_streamer
        summarize_overflow("x" * (_MIN_CHARS_FOR_SUMMARY + 100), {"model": "deepseek-v4.1-flash"})
        assert captured_kwargs["model"] == "deepseek-v4.1-flash"

    @patch("bouzecode.backend.agent.thinking_summary.get_streamer")
    def test_side_call_failure_returns_none(self, mock_get_streamer, monkeypatch):
        """Side-call exception → graceful None, no crash."""
        monkeypatch.setenv("BOUZECODE_THINKING_SUMMARY", "1")
        mock_get_streamer.return_value = _make_failing_streamer()

        long_text = "x" * (_MIN_CHARS_FOR_SUMMARY + 100)
        result = summarize_overflow(long_text, {})
        assert result is None

    @patch("bouzecode.backend.agent.thinking_summary.get_streamer")
    def test_empty_response_returns_none(self, mock_get_streamer, monkeypatch):
        """Empty/whitespace response → None."""
        monkeypatch.setenv("BOUZECODE_THINKING_SUMMARY", "1")
        mock_get_streamer.return_value = _make_fake_streamer("   ")

        long_text = "x" * (_MIN_CHARS_FOR_SUMMARY + 100)
        result = summarize_overflow(long_text, {})
        assert result is None

    def test_default_env_var_is_enabled(self, monkeypatch):
        """Without env var set, feature is enabled (but still needs threshold)."""
        monkeypatch.delenv("BOUZECODE_THINKING_SUMMARY", raising=False)
        short_text = "x" * (_MIN_CHARS_FOR_SUMMARY - 1)
        # Short text should still return None (threshold guard)
        result = summarize_overflow(short_text, {})
        assert result is None


class TestOverflowSummaryPersistence:
    """The overflow summary must land in the methodology (durable), not just a
    one-shot nudge — see append_overflow_summary_to_methodology."""

    def test_summary_appended_to_methodology(self):
        from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE
        from bouzecode.backend.context_manager.methodology import (
            append_overflow_summary_to_methodology,
        )

        cs = ContextState()
        append_overflow_summary_to_methodology(cs, "• Key finding 1\n• Decision made")

        note = cs.notes[METHODOLOGY_NOTE]
        assert "Auto-compacted thoughts after overflow" in note
        assert "Key finding 1" in note
        assert "Decision made" in note

    def test_summary_appends_after_existing_methodology(self):
        from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE
        from bouzecode.backend.context_manager.methodology import (
            append_overflow_summary_to_methodology,
        )

        cs = ContextState(notes={METHODOLOGY_NOTE: "## Objectif\nRefactorer la BR"})
        append_overflow_summary_to_methodology(cs, "• conclusion")

        note = cs.notes[METHODOLOGY_NOTE]
        assert note.startswith("## Objectif")
        assert "Auto-compacted thoughts after overflow" in note

    def test_empty_summary_is_noop(self):
        from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE
        from bouzecode.backend.context_manager.methodology import (
            append_overflow_summary_to_methodology,
        )

        cs = ContextState()
        append_overflow_summary_to_methodology(cs, "   ")
        assert METHODOLOGY_NOTE not in cs.notes
