"""Verify providers module location after refactoring."""
import importlib
import pytest


def test_providers_importable_from_backend():
    """bouzecode.backend.agent.providers must be importable with all key symbols."""
    from bouzecode.backend.agent.providers import (
        stream, AssistantTurn, TextChunk, ThinkingChunk,
        ToolCallParsed, ToolIdRemap, StreamStarted, SystemPayload,
        bare_model, get_api_key, calc_cost, MODELS,
        messages_to_anthropic, sanitize_messages,
    )
    assert callable(stream)
    assert callable(bare_model)


def test_old_agent_providers_not_importable():
    """The old top-level bouzecode.providers path must not exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bouzecode.providers")


def test_only_anthropic_models():
    """The model registry holds only supported socle models (Claude + DeepSeek)."""
    from bouzecode.backend.agent.providers import MODELS
    assert all(m.startswith(("claude-", "deepseek-")) for m in MODELS)


def test_agent_imports_cleanly():
    """The agent package must import without errors."""
    from bouzecode.backend.agent import run, AgentState, TextChunk
    assert callable(run)


def test_stream_function_exists():
    """stream() must be accessible from the new location."""
    from bouzecode.backend.agent.providers.backends.dispatch import stream
    assert callable(stream)
