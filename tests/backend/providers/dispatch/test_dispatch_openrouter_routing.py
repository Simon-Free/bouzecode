# [desc] Tests dispatch.stream() provider routing for DeepSeek/OpenRouter vs Anthropic paths based on env keys
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests dispatch.stream() provider routing for DeepSeek/OpenRouter vs Anthropic paths based on env keys</param></tool_use> [/desc]
"""Test dispatch.stream() provider routing for the DeepSeek/OpenRouter path."""
import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.types import SystemPayload


def _first_event(model: str, config: dict):
    gen = stream(
        model=model,
        system="SYS",
        messages=[{"role": "user", "content": "Hello"}],
        tool_schemas=[],
        config=config,
    )
    try:
        return next(gen)
    finally:
        gen.close()


def test_missing_openrouter_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OpenRouter"):
        _first_event("deepseek-v4-flash", {})


def test_deepseek_routes_without_anthropic_key(monkeypatch):
    # Even with no Anthropic key, DeepSeek must route via OpenRouter and reach
    # the SystemPayload (the OpenRouter call itself is never triggered here).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    first = _first_event("deepseek-v4-flash", {})
    assert isinstance(first, SystemPayload)


def test_anthropic_still_routes_with_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    first = _first_event("claude-3-5-sonnet-20241022", {})
    assert isinstance(first, SystemPayload)
