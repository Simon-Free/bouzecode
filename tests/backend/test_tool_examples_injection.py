# [desc] Tests that tool usage examples are correctly injected into system prompts per model provider. [/desc]
"""Tests for dynamic tool examples injection in system prompt.

Since dc56090 the example is trimmed to the single complete-response turn
(Methodology + Snippet + Edit + RunPythonTest); WritePlan is no longer part of
it. The provider-specific format (XML vs JSON) is the contract under test.
"""
from bouzecode.backend.core.context import build_system_prompt_parts


def test_xml_examples_injected_for_anthropic_model():
    """Claude models get the XML full-turn example."""
    stable, _ = build_system_prompt_parts({"model": "claude-sonnet-4-6"})
    assert '<tool_use name="Methodology"' in stable
    assert '<tool_use name="Edit"' in stable
    assert "{tool_examples}" not in stable


def test_json_examples_injected_for_openrouter_model():
    """DeepSeek/OpenRouter models get the JSON (OpenAI tool_calls) example."""
    stable, _ = build_system_prompt_parts({"model": "deepseek/deepseek-r1"})
    assert '"name": "Methodology"' in stable
    assert '"tool_calls"' in stable
    assert "<tool_use" not in stable
    assert "{tool_examples}" not in stable


def test_no_pseudo_python_in_any_provider():
    """No pseudo-Python syntax remains in the output for any provider."""
    for model in ("claude-sonnet-4-6", "deepseek/deepseek-r1"):
        stable, _ = build_system_prompt_parts({"model": model})
        assert 'WritePlan(content="' not in stable
        assert 'Edit(file_path="' not in stable
        assert 'Write(file_path="temp_check.py", content="' not in stable


def test_placeholder_fully_replaced():
    """The {tool_examples} placeholder never appears in final output."""
    for model in ("claude-sonnet-4-6", "deepseek/deepseek-r1", ""):
        stable, _ = build_system_prompt_parts({"model": model})
        assert "{tool_examples}" not in stable
