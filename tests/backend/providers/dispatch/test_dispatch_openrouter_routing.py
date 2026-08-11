# [desc] Tests that dispatch.stream() routes DeepSeek to OpenRouter and errors clearly without a key. [/desc]
"""Test dispatch.stream() provider routing for the DeepSeek/OpenRouter path."""
import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.missing_key import MissingApiKeyError
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
    """The diagnosis names the provider, the model and the variable to set.

    It is a MissingApiKeyError (a RuntimeError) so the CLI can print it without
    a traceback — see tests/backend/providers/test_missing_api_key_message.py."""
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(MissingApiKeyError) as raised:
        _first_event("deepseek-v4-flash", {})

    message = str(raised.value)
    assert "openrouter" in message
    assert "deepseek-v4-flash" in message
    assert "OPENROUTER_KEY=sk-or-..." in message


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
