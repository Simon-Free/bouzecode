# [desc] Tests that dispatch.stream() respects custom vs default system prompt override in Anthropic path
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that dispatch.stream() respects custom vs default system prompt override in Anthropic path</param></tool_use> [/desc]
"""Test that dispatch.stream() uses the system param when provided (Anthropic path)."""
import os

import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.types import SystemPayload


@pytest.fixture(autouse=True)
def _fake_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")


def _get_system_payload(system: str, config: dict | None = None) -> SystemPayload:
    """Call stream() and return the first SystemPayload yielded."""
    gen = stream(
        model="anthropic/claude-3-5-sonnet-20241022",
        system=system,
        messages=[{"role": "user", "content": "Hello"}],
        tool_schemas=[],
        config=config or {},
    )
    first = next(gen)
    gen.close()
    assert isinstance(first, SystemPayload), f"Expected SystemPayload, got {type(first)}"
    return first


def test_custom_system_prompt_used_when_provided():
    """When system param is non-empty, it should be used as stable_prefix."""
    payload = _get_system_payload("CUSTOM_FOCUS_PROMPT")
    first_block_text = payload.system_blocks[0]["text"]
    assert "CUSTOM_FOCUS_PROMPT" in first_block_text, (
        f"Custom system prompt not found in first block. Got: {first_block_text[:200]}"
    )


def test_custom_system_prompt_excludes_bouzecode_standard():
    """When system param is provided, bouzecode standard prose should NOT appear."""
    payload = _get_system_payload("CUSTOM_FOCUS_PROMPT")
    first_block_text = payload.system_blocks[0]["text"]
    # The standard bouzecode template contains this unique marker
    assert "Bouzecode" not in first_block_text and "bouzecode" not in first_block_text.lower().replace("custom_focus_prompt", ""), (
        f"Bouzecode standard prose leaked into custom system prompt block"
    )


def test_default_system_prompt_when_empty():
    """When system param is empty, build_system_prompt_parts should be used."""
    payload = _get_system_payload("")
    first_block_text = payload.system_blocks[0]["text"]
    # The standard template should be present (contains platform hints, etc.)
    assert len(first_block_text) > 100, "Default system prompt should be substantial"
