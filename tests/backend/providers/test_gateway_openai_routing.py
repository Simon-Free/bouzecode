# [desc] Tests routing gateway_openai: gpt-5.6-luna/sol/terra vers OpenAI-compat prod + non-régression claude/pp/openrouter. [/desc]
"""Routing for the internal LLM gateway PROD OpenAI-compatible models (gpt-5.6-luna/sol/terra).

These models are served by the prod gateway ONLY on /v1/chat/completions (OpenAI);
its Anthropic pass-through crashes in streaming, so they must NOT fall through to
the anthropic provider — they route to gateway_openai (OpenAI transport, prod endpoint).
"""
import pytest

from bouzecode.backend.agent.providers.registry import (
    resolve_provider, get_provider_key, PROVIDERS,
)


@pytest.mark.parametrize("model", [
    "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra",
])
def test_prod_openai_models_route_to_gateway_openai(model):
    provider, model_id = resolve_provider(model)
    assert provider == "gateway_openai"
    assert model_id == model  # verbatim id for the OpenAI-compat proxy


def test_gateway_openai_explicit_prefix_is_stripped():
    assert resolve_provider("gateway_openai/gpt-5.6-sol") == ("gateway_openai", "gpt-5.6-sol")


def test_gateway_openai_key_uses_anthropic_auth_token(monkeypatch):
    # gateway_openai reuses the prod gateway auth (get_api_key → ANTHROPIC_AUTH_TOKEN).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-prod-fake")
    assert get_provider_key("gateway_openai", {}) == "sk-prod-fake"


def test_gateway_openai_models_listed_in_provider():
    for m in ("gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"):
        assert m in PROVIDERS["gateway_openai"]["models"]


# --- non-regression: existing routing must be untouched ---

def test_prod_claude_stays_anthropic():
    assert resolve_provider("claude-opus-4-6")[0] == "anthropic"


def test_preprod_gpt55_stays_gateway_preprod():
    assert resolve_provider("gpt-5.5")[0] == "gateway_preprod"


def test_deepseek_stays_openrouter():
    assert resolve_provider("deepseek-v4-flash")[0] == "openrouter"
