# [desc] claude-sonnet-5-5: routed verbatim to gateway_preprod (preprod only), native tools, priced $2/$10 [/desc]
"""claude-sonnet-5-5 is served by the preprod gateway only (GET /v1/models, 2026-10-05),
so it routes to the OpenAI-compatible "gateway_preprod" provider with its verbatim id."""
import pytest

from bouzecode.backend.agent.providers.registry import (
    PROVIDERS, resolve_provider, model_uses_native_tools, calc_cost, is_priced,
)

MODEL = "claude-sonnet-5-5"


def test_sonnet_5_5_listed_in_gateway_preprod_only():
    assert MODEL in PROVIDERS["gateway_preprod"]["models"]
    assert MODEL not in PROVIDERS["anthropic"]["models"]


def test_sonnet_5_5_routes_to_gateway_preprod_verbatim():
    assert resolve_provider(MODEL) == ("gateway_preprod", MODEL)
    assert resolve_provider(f"gateway_preprod/{MODEL}") == ("gateway_preprod", MODEL)


def test_sonnet_5_5_uses_native_tools():
    assert model_uses_native_tools(MODEL, {}) is True


def test_sonnet_5_5_is_priced_at_list_price():
    assert is_priced(MODEL) is True
    assert calc_cost(MODEL, 1_000_000, 0) == pytest.approx(2.0)
    assert calc_cost(MODEL, 0, 1_000_000) == pytest.approx(10.0)


def test_sonnet_5_does_not_follow_sonnet_5_5():
    """The prefix match must not drag claude-sonnet-5 (prod gateway) to the preprod."""
    assert resolve_provider("claude-sonnet-5")[0] != "gateway_preprod"
