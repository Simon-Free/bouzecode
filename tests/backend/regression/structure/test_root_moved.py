"""Verify that root files have been moved to core/ and agent/."""
import importlib
import pytest


def test_core_config_importable():
    """config.py must be importable from core/."""
    from bouzecode.backend.core.config import load_config
    assert callable(load_config)


def test_core_context_importable():
    """context.py must be importable from core/."""
    from bouzecode.backend.core.context import build_system_prompt_parts
    assert callable(build_system_prompt_parts)


def test_core_tool_registry_importable():
    """tool_registry.py must be importable from core/."""
    from bouzecode.backend.core.tool_registry import register_tool, get_all_tools
    assert callable(register_tool)
    assert callable(get_all_tools)


def test_core_paths_importable():
    """paths.py must be importable from core/."""
    from bouzecode.backend.core.paths import register_extra_dirs, get_extra_dirs
    assert callable(register_extra_dirs)
    assert callable(get_extra_dirs)


def test_agent_compaction_importable():
    """compaction.py must be importable from agent/."""
    from bouzecode.backend.agent.compaction import estimate_tokens
    assert callable(estimate_tokens)


def test_agent_minimal_payload_importable():
    """minimal_payload.py must be importable from agent/."""
    from bouzecode.backend.agent.minimal_payload import build_messages_for_api
    assert callable(build_messages_for_api)


def test_agent_providers_importable():
    """providers must be importable from agent/providers/."""
    from bouzecode.backend.agent.providers import (
        stream, AssistantTurn, TextChunk, ThinkingChunk,
        ToolCallParsed, ToolIdRemap, StreamStarted, SystemPayload,
        bare_model, get_api_key, calc_cost, MODELS,
        messages_to_anthropic, sanitize_messages,
    )
    assert callable(stream)
    assert callable(bare_model)


def test_only_anthropic_models():
    """The model registry holds only supported socle models (Claude + DeepSeek)."""
    from bouzecode.backend.agent.providers import MODELS
    assert all(m.startswith(("claude-", "deepseek-")) for m in MODELS)


def test_old_root_paths_dead():
    """Old root-level modules must not be importable from backend root."""
    dead_modules = [
        "bouzecode.backend.config",
        "bouzecode.backend.context",
        "bouzecode.backend.paths",
        "bouzecode.backend.tool_registry",
        "bouzecode.backend.compaction",
        "bouzecode.backend.minimal_payload",
        "bouzecode.backend.providers",
    ]
    for mod in dead_modules:
        with pytest.raises(ModuleNotFoundError, match=mod.split(".")[-1]):
            importlib.import_module(mod)
