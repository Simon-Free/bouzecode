# [desc] claude-opus-5-5: routed verbatim to gateway_preprod, native tools, priced, default model of bouzecode, no ttl 1h on the preprod [/desc]
"""claude-opus-5-5 is served by the preprod gateway only (not by the prod gateway),
so it must route to the OpenAI-compatible "gateway_preprod" provider, verbatim id."""
import pytest

from bouzecode.backend.agent.providers.registry import (
    PROVIDERS, resolve_provider, model_uses_native_tools, calc_cost, is_priced,
)

MODEL = "claude-opus-5-5"


def test_opus_5_5_listed_in_gateway_preprod_only():
    assert MODEL in PROVIDERS["gateway_preprod"]["models"]
    assert MODEL not in PROVIDERS["anthropic"]["models"]


def test_opus_5_5_routes_to_gateway_preprod_verbatim():
    assert resolve_provider(MODEL) == ("gateway_preprod", MODEL)


def test_opus_5_5_explicit_prefix_is_stripped():
    assert resolve_provider(f"gateway_preprod/{MODEL}") == ("gateway_preprod", MODEL)


def test_opus_5_5_uses_native_tools():
    assert model_uses_native_tools(MODEL, {}) is True


def test_opus_5_5_is_priced_like_opus_on_the_gateway():
    assert is_priced(MODEL) is True
    assert calc_cost(MODEL, 1_000_000, 0) == pytest.approx(4.7)
    assert calc_cost(MODEL, 0, 1_000_000) == pytest.approx(23.33)


def test_opus_5_5_is_the_default_model_and_side_calls_follow_it():
    from bouzecode.backend.core.config import DEFAULTS
    from bouzecode.backend.agent.providers.side_model import modele_annexe
    assert DEFAULTS["model"] == MODEL
    assert modele_annexe({}) == MODEL
    assert resolve_provider(modele_annexe(None)) == ("gateway_preprod", MODEL)


def test_gateway_preprod_cache_policy_follows_preprod_not_anthropic_url(monkeypatch):
    """Without ANTHROPIC_BASE_URL a gateway_preprod session passed for the official API and sent
    ttl 1h: the preprod gateway answers content_filter to that on claude-opus-5-5."""
    from bouzecode.backend.agent.providers.backends.dispatch import (
        provider_base_url, _resolve_cache_control,
    )
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("BOUZECODE_CACHE_TTL_1H", raising=False)
    monkeypatch.setenv("PREPROD_ENDPOINT", "https://preprod.gateway.example")
    assert provider_base_url("gateway_preprod") == "https://preprod.gateway.example"
    assert _resolve_cache_control(provider_base_url("gateway_preprod")) == {"type": "ephemeral"}
