# [desc] Tests that _build_assistant_content correctly prepends thinking blocks into saved assistant message content [/desc]
"""Test that thinking_parts are saved into the assistant message content.

Bug: in extended thinking mode, ctx.thinking_parts accumulates thinking but
loop.py L207-209 saves only at.text (which is "." placeholder), losing the thinking.
This test imports _build_assistant_content which must prepend <thinking> tags.
"""
import pytest

from bouzecode.backend.agent.loop import _build_assistant_content


class TestBuildAssistantContent:
    """_build_assistant_content must include thinking when present."""

    def test_thinking_prepended_to_text(self):
        """When thinking_parts is non-empty, content must start with <thinking> block."""
        result = _build_assistant_content("Some response", ["First thought\n", "Second thought"])
        assert "<thinking>" in result
        assert "First thought" in result
        assert "Second thought" in result
        assert "Some response" in result

    def test_dot_placeholder_removed_when_only_thinking(self):
        """When at.text is just '.' (placeholder), it should be excluded from content."""
        result = _build_assistant_content(".", ["My deep thinking here"])
        assert "<thinking>" in result
        assert "My deep thinking here" in result
        assert result.strip() != "."
        # The dot should not appear as meaningful content
        assert not result.endswith(".")

    def test_no_thinking_returns_text_unchanged(self):
        """When thinking_parts is empty, content is just at.text unchanged."""
        result = _build_assistant_content("Normal response", [])
        assert result == "Normal response"

    def test_empty_thinking_parts_no_tags(self):
        """Empty list should not produce <thinking> tags."""
        result = _build_assistant_content("Hello", [])
        assert "<thinking>" not in result

    def test_thinking_with_empty_text(self):
        """When at.text is empty but thinking exists, only thinking is saved."""
        result = _build_assistant_content("", ["Some thought"])
        assert "<thinking>" in result
        assert "Some thought" in result
