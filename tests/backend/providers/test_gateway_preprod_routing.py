# [desc] Tests routing of preprod-only gateway models to gateway_preprod and Kimi to OpenRouter. [/desc]
"""Routing for the internal LLM gateway preprod (OpenAI-compatible) and Kimi K2.7-Code."""
import pytest

from bouzecode.backend.agent.providers.registry import (
    resolve_provider, model_uses_native_tools, get_provider_key, PROVIDERS,
)
from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.types import SystemPayload


def _first_event(model: str, config: dict):
    gen = stream(model=model, system="SYS",
                 messages=[{"role": "user", "content": "Hi"}],
                 tool_schemas=[], config=config)
    try:
        return next(gen)
    finally:
        gen.close()


# --- gateway preprod routing ---

@pytest.mark.parametrize("model", [
    "gpt-5.5", "gpt-5.5-2026-04-24", "mistral-medium-3-5",
    "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-embedding-2",
])
def test_preprod_only_models_route_to_gateway_preprod(model):
    provider, model_id = resolve_provider(model)
    assert provider == "gateway_preprod"
    assert model_id == model  # verbatim id for the LiteLLM proxy


def test_gateway_preprod_explicit_prefix_is_stripped():
    assert resolve_provider("gateway_preprod/gpt-5.5") == ("gateway_preprod", "gpt-5.5")


def test_gateway_preprod_uses_native_tools():
    assert model_uses_native_tools("gpt-5.5", {}) is True


def test_gateway_preprod_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY_PP", "sk-pp-fake")
    assert get_provider_key("gateway_preprod", {}) == "sk-pp-fake"


def test_missing_gateway_preprod_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY_PP", raising=False)
    with pytest.raises(RuntimeError, match="preprod"):
        _first_event("gpt-5.5", {})


def test_gateway_preprod_routes_without_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY_PP", "sk-pp-fake")
    assert isinstance(_first_event("gpt-5.5", {}), SystemPayload)


def test_prod_claude_not_routed_to_preprod():
    # claude-opus-4-6 is prod-only; it must stay on the anthropic gateway.
    assert resolve_provider("claude-opus-4-6")[0] == "anthropic"


# --- claude-opus-5 / claude-sonnet-5 on the PROD anthropic gateway ---
# Requalified 2026-08-20: the prod gateway serves both on /v1/messages with native
# streaming tool_use, so they must NOT go through the OpenAI transport anymore.

@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-5"])
def test_claude_5_routes_to_anthropic(model):
    assert resolve_provider(model) == ("anthropic", model)


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-5"])
def test_claude_5_listed_in_anthropic_provider(model):
    assert model in PROVIDERS["anthropic"]["models"]
    assert model not in PROVIDERS["gateway_preprod"]["models"]


def test_claude_5_uses_native_tools_on_the_gateway(monkeypatch):
    # The prod gateway is a known native-tool_use endpoint (probed 2026-08-20:
    # streaming tool_use blocks well formed for both claude-5 models), so the
    # capability must be recognised. Whether native tools are actually USED is a
    # separate, endpoint-wide policy (_NATIVE_TOOLS_DEFAULT_ON + the env switch),
    # which this test deliberately does not freeze: it pins the switch to "1" and
    # only checks that the anthropic route can serve native tools for claude-5.
    from bouzecode.backend.agent.providers.registry import (
        anthropic_endpoint_serves_native_tools,
    )
    assert anthropic_endpoint_serves_native_tools("https://llm-gateway.example.com") is True
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://llm-gateway.example.com")
    assert model_uses_native_tools("claude-opus-5", {}) is True
    assert model_uses_native_tools("claude-sonnet-5", {}) is True


def test_claude_5_has_cost():
    from bouzecode.backend.agent.providers.registry import calc_cost
    assert calc_cost("claude-opus-5", 1_000_000, 0) == pytest.approx(4.7)
    assert calc_cost("claude-sonnet-5", 1_000_000, 0) == pytest.approx(2.8)
    assert calc_cost("claude-sonnet-5", 0, 1_000_000) == pytest.approx(14.0)


# --- Kimi K2.7-Code via OpenRouter ---

def test_kimi_maps_to_openrouter_slug():
    provider, model_id = resolve_provider("kimi-k2.7-code")
    assert provider == "openrouter"
    assert model_id == "moonshotai/kimi-k2.7-code"


def test_kimi_uses_native_tools():
    assert model_uses_native_tools("kimi-k2.7-code", {}) is True


def test_kimi_listed_in_openrouter_provider():
    assert "kimi-k2.7-code" in PROVIDERS["openrouter"]["models"]


def test_kimi_cost_cache_miss_input_and_output():
    from bouzecode.backend.agent.providers.registry import calc_cost
    assert calc_cost("kimi-k2.7-code", 1_000_000, 0) == pytest.approx(0.95)
    assert calc_cost("kimi-k2.7-code", 0, 1_000_000) == pytest.approx(4.0)


def test_kimi_cost_cache_hit_uses_absolute_override():
    from bouzecode.backend.agent.providers.registry import calc_cost
    # in_tok EXCLUT la lecture de cache (convention de la chaîne) ; lu en cache : $0.19/M.
    cost = calc_cost("kimi-k2.7-code", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.19)


# --- GLM 5.2 via OpenRouter ---

def test_glm_maps_to_openrouter_slug():
    provider, model_id = resolve_provider("glm-5.2")
    assert provider == "openrouter"
    assert model_id == "z-ai/glm-5.2"


def test_glm_uses_native_tools():
    assert model_uses_native_tools("glm-5.2", {}) is True


def test_glm_listed_in_openrouter_provider():
    assert "glm-5.2" in PROVIDERS["openrouter"]["models"]


# --- GLM 5.3 Flash via OpenRouter ---
# Same vendor prefix as glm-5.2 (z-ai/). Pricing left unconfirmed on purpose:
# Pricing confirmed 2026-08-27 against GET openrouter.ai/api/v1/models (reached
# through the local px NTLM relay): z-ai/glm-5.3-flash bills $0.075/M input and
# $0.25/M output, so the model must report as priced.

def test_glm_53_flash_maps_to_openrouter_slug():
    provider, model_id = resolve_provider("glm-5.3-flash")
    assert provider == "openrouter"
    assert model_id == "z-ai/glm-5.3-flash"


def test_glm_53_flash_uses_native_tools():
    assert model_uses_native_tools("glm-5.3-flash", {}) is True


def test_glm_53_flash_listed_in_openrouter_provider():
    assert "glm-5.3-flash" in PROVIDERS["openrouter"]["models"]


def test_glm_53_flash_is_priced():
    from bouzecode.backend.agent.providers.registry import is_priced
    assert is_priced("glm-5.3-flash") is True


def test_glm_53_flash_cost_matches_openrouter_rates():
    from bouzecode.backend.agent.providers.registry import calc_cost
    assert calc_cost("glm-5.3-flash", 1_000_000, 0) == pytest.approx(0.075)
    assert calc_cost("glm-5.3-flash", 0, 1_000_000) == pytest.approx(0.25)
