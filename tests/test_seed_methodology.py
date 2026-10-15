"""Tests for seed methodology placeholder (BOUZECODE_SEED_METHODOLOGY).

Validates that when methodology_text is empty, a placeholder block is
injected to reduce first-turn tool-call omission (82% → near 0%).

Since 2026-10-07 the note (and so its placeholder) travels in <working_notes> at the head of
the first user message, no longer in the system (content_filter refusals of claude-opus-5-5).
"""
from __future__ import annotations

import os
import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.context_manager.state import ContextState, METHODOLOGY_NOTE


# Un tour d'AGENT porte toujours ses outils ; un appel sans outils est un appel annexe
# (compaction, juge…), qui ne recoit pas le gabarit de note vide.
_OUTILS_AGENT = [{"name": "Methodology", "description": "note de travail",
                  "input_schema": {"type": "object", "properties": {}}}]


def _make_config(context_state=None, depth=0):
    """Minimal config dict for dispatch.stream()."""
    return {
        "_context_state": context_state,
        "_depth": depth,
    }


def _collect_system_blocks(gen):
    """Consume the first yield (SystemPayload) and return the note blocks: the content parts
    of the first user message (<working_notes>), after a check that the system has none."""
    payload = next(gen)
    assert not any("Note vide" in b.get("text", "") for b in payload.system_blocks)
    content = payload.messages[0]["content"]
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


class TestSeedMethodologyPlaceholder:
    """When methodology is empty, a placeholder block must appear."""

    def test_placeholder_present_when_methodology_empty(self, monkeypatch):
        """Empty methodology → placeholder block in system_blocks."""
        monkeypatch.setenv("BOUZECODE_SEED_METHODOLOGY", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

        gc = ContextState()
        # Ensure methodology is empty
        assert gc.notes.get(METHODOLOGY_NOTE, "") == ""

        config = _make_config(context_state=gc)
        messages = [{"role": "user", "content": "hello"}]

        gen = stream(
            model="anthropic/claude-sonnet-4-20250514",
            system="",
            messages=messages,
            tool_schemas=_OUTILS_AGENT,
            config=config,
        )
        blocks = _collect_system_blocks(gen)

        # Find the placeholder block (use unique marker text)
        placeholder_blocks = [
            b for b in blocks
            if "text" in b and "Note vide" in b.get("text", "")
        ]
        assert len(placeholder_blocks) == 1, (
            f"Expected exactly 1 placeholder block, got {len(placeholder_blocks)}"
        )
        placeholder_text = placeholder_blocks[0]["text"]

        # Must contain the methodology header
        assert "[METHODOLOGY" in placeholder_text

        # Must contain exact XML tool_use syntax
        assert '<tool_use name="Methodology"' in placeholder_text
        assert '<param name="content">' in placeholder_text

        # Must NOT have cache_control (transitoire)
        assert "cache_control" not in placeholder_blocks[0]

    def test_no_placeholder_when_methodology_nonempty(self, monkeypatch):
        """Non-empty methodology → normal meth blocks, NO placeholder."""
        monkeypatch.setenv("BOUZECODE_SEED_METHODOLOGY", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

        gc = ContextState()
        gc.notes[METHODOLOGY_NOTE] = "## Some existing notes\nHello world"

        config = _make_config(context_state=gc)
        messages = [{"role": "user", "content": "hello"}]

        gen = stream(
            model="anthropic/claude-sonnet-4-20250514",
            system="",
            messages=messages,
            tool_schemas=_OUTILS_AGENT,
            config=config,
        )
        blocks = _collect_system_blocks(gen)

        # Should have real methodology block with the content
        meth_blocks = [
            b for b in blocks
            if "text" in b and "Some existing notes" in b.get("text", "")
        ]
        assert len(meth_blocks) >= 1

        # Should NOT have placeholder syntax
        all_text = " ".join(b.get("text", "") for b in blocks)
        assert "Note vide" not in all_text

    def test_flag_disabled_no_placeholder(self, monkeypatch):
        """BOUZECODE_SEED_METHODOLOGY=0 → no placeholder even when empty."""
        monkeypatch.setenv("BOUZECODE_SEED_METHODOLOGY", "0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

        gc = ContextState()
        config = _make_config(context_state=gc)
        messages = [{"role": "user", "content": "hello"}]

        gen = stream(
            model="anthropic/claude-sonnet-4-20250514",
            system="",
            messages=messages,
            tool_schemas=_OUTILS_AGENT,
            config=config,
        )
        blocks = _collect_system_blocks(gen)

        # No placeholder
        placeholder_blocks = [
            b for b in blocks
            if "text" in b and "Note vide" in b.get("text", "")
        ]
        assert len(placeholder_blocks) == 0

    def test_placeholder_opens_the_working_notes(self, monkeypatch):
        """Placeholder opens <working_notes>, at the head of the first user message."""
        monkeypatch.setenv("BOUZECODE_SEED_METHODOLOGY", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

        gc = ContextState()
        config = _make_config(context_state=gc)
        messages = [{"role": "user", "content": "hello"}]

        gen = stream(
            model="anthropic/claude-sonnet-4-20250514",
            system="",
            messages=messages,
            tool_schemas=_OUTILS_AGENT,
            config=config,
        )
        blocks = _collect_system_blocks(gen)

        # Find placeholder index
        placeholder_idx = None
        for i, b in enumerate(blocks):
            if "text" in b and "Note vide" in b.get("text", ""):
                placeholder_idx = i
                break

        assert placeholder_idx is not None
        # The placeholder opens the <working_notes> envelope of the first user message.
        assert placeholder_idx == 0
        assert blocks[0]["text"].startswith("<working_notes>\n[METHODOLOGY")

    def test_methodology_note_not_seeded(self, monkeypatch):
        """Placeholder must NOT write into context_state.notes[METHODOLOGY_NOTE]."""
        monkeypatch.setenv("BOUZECODE_SEED_METHODOLOGY", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

        gc = ContextState()
        config = _make_config(context_state=gc)
        messages = [{"role": "user", "content": "hello"}]

        gen = stream(
            model="anthropic/claude-sonnet-4-20250514",
            system="",
            messages=messages,
            tool_schemas=_OUTILS_AGENT,
            config=config,
        )
        _collect_system_blocks(gen)

        # context_state must remain untouched
        assert gc.notes.get(METHODOLOGY_NOTE, "") == ""
