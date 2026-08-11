# [desc] A missing provider key produces an actionable diagnosis, not a bare "No Anthropic API key found" + traceback. [/desc]
"""What a newcomer sees when only OPENROUTER_KEY is set.

Before: the launcher printed "WARNING: ANTHROPIC_API_KEY not set" even though
OpenRouter was configured and working, and the first prompt died on
`RuntimeError: No Anthropic API key found` under a 25-line traceback that said
nothing about the key the user DID have.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.missing_key import (
    MissingApiKeyError,
    configured_providers,
    missing_key_message,
    startup_key_warning,
)

_KEY_ENV_VARS = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "OPENROUTER_KEY", "OPENROUTER_API_KEY",
    "BOUZECODE_GATEWAY_API_KEY",
)


@pytest.fixture
def no_provider_keys(monkeypatch):
    """A machine with no credentials at all."""
    for name in _KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return {}


@pytest.fixture
def only_openrouter(no_provider_keys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    return {}


def test_only_the_providers_that_hold_a_key_are_reported(only_openrouter):
    assert configured_providers(only_openrouter) == ["openrouter"]


def test_the_diagnosis_names_the_configured_provider_and_a_model_to_use(only_openrouter):
    message = missing_key_message("anthropic", "claude-opus-4-8", only_openrouter)

    assert "claude-opus-4-8" in message
    assert "openrouter" in message
    assert "--model deepseek-v4-flash" in message
    assert "ANTHROPIC_API_KEY=sk-ant-..." in message


def test_with_no_key_at_all_the_diagnosis_lists_every_provider(no_provider_keys):
    message = missing_key_message("anthropic", "claude-opus-4-8", no_provider_keys)

    assert "No provider is configured at all." in message
    assert "ANTHROPIC_API_KEY=sk-ant-..." in message
    assert "OPENROUTER_KEY=sk-or-..." in message


def test_the_launch_warning_stays_silent_when_the_model_can_run(only_openrouter):
    assert startup_key_warning("deepseek-v4-flash", only_openrouter) is None


def test_the_launch_warning_names_the_key_the_user_already_has(only_openrouter):
    warning = startup_key_warning("claude-opus-4-8", only_openrouter)

    assert warning is not None
    assert "openrouter" in warning
    assert "--model deepseek-v4-flash" in warning


def test_a_turn_without_a_key_raises_the_configuration_error(only_openrouter):
    """MissingApiKeyError is what the CLI catches to skip the traceback."""
    turn = stream(
        model="claude-opus-4-8", system="hi", messages=[{"role": "user", "content": "x"}],
        tool_schemas=[], config=only_openrouter,
    )

    with pytest.raises(MissingApiKeyError) as raised:
        next(turn)

    assert "openrouter" in str(raised.value)
