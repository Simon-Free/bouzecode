# [desc] Tests system prompt template loading, build_system_prompt_parts output, plan mode injection, and platform hints
# <tool_use name="FinalAnswer" id="1"><param name="answer">Tests system prompt template loading, build_system_prompt_parts output, plan mode injection, and platform hints</param></tool_use> [/desc]
"""Tests for system prompt loading from .txt files."""


def test_embedded_data_exports_all_prompts():
    from bouzecode.backend.core._embedded_data import (
        SYSTEM_PROMPT_TEMPLATE,
        THINK_OUT_LOUD_PROMPT,
        WINDOWS_PLATFORM_HINTS,
        PLAN_MODE_TEMPLATE,
        MEMORY_CONSOLIDATION_PROMPT,
        COMPACTION_SYSTEM_PROMPT,
    )
    assert "<thinking>...</thinking>" in THINK_OUT_LOUD_PROMPT
    assert "Windows Shell Hints" in WINDOWS_PLATFORM_HINTS
    assert "{plan_file}" in PLAN_MODE_TEMPLATE
    assert "memory consolidation assistant" in MEMORY_CONSOLIDATION_PROMPT
    assert COMPACTION_SYSTEM_PROMPT == "You are a concise summarizer."
    assert "Bouzecode" in SYSTEM_PROMPT_TEMPLATE


def test_build_system_prompt_contains_loaded_prompts():
    from bouzecode.backend.core.context import build_system_prompt_parts
    stable, volatile = build_system_prompt_parts(config={"thinking": True, "thinking_mode": "loud"})
    # The noyau is agnostic: code-specific sections (symbol reading, discovery) now
    # live in the default profile, not in the shared base.
    assert "Un tour ressemble TOUJOURS" in stable
    assert "Symbol-Aware Code Reading" not in stable
    assert "<thinking>...</thinking>" in stable


def test_build_system_prompt_plan_mode():
    from bouzecode.backend.core.context import build_system_prompt_parts
    stable, volatile = build_system_prompt_parts(config={"permission_mode": "plan", "_plan_file": "test_plan.md"})
    assert "test_plan.md" in volatile
    assert "Plan Mode (ACTIVE)" in volatile


def test_platform_hints_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    from bouzecode.backend.core.context import get_platform_hints
    result = get_platform_hints()
    assert "Windows Shell Hints" in result
    assert "type file.txt" in result
