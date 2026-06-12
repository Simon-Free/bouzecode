# [desc] Tests provider routing and DeepSeek/OpenRouter cost calculation in the registry.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests provider routing and DeepSeek/OpenRouter cost calculation in the registry.</param></tool_use> [/desc]
"""Tests for resolve_provider and calc_cost with the DeepSeek V4 Flash model."""
import pytest

from bouzecode.backend.agent.providers.registry import resolve_provider, calc_cost


def test_resolve_provider_deepseek_maps_to_openrouter_slug():
    provider, model_id = resolve_provider("deepseek-v4-flash")
    assert provider == "openrouter"
    assert model_id == "deepseek/deepseek-v4-flash"


def test_resolve_provider_anthropic_is_default():
    provider, model_id = resolve_provider("claude-opus-4-6")
    assert provider == "anthropic"
    assert model_id == "claude-opus-4-6"


def test_resolve_provider_strips_slash_prefix_for_anthropic():
    provider, model_id = resolve_provider("anthropic/claude-3-5-sonnet-20241022")
    assert provider == "anthropic"
    assert model_id == "claude-3-5-sonnet-20241022"


def test_calc_cost_deepseek_input_only():
    # 1M pure input tokens at $0.0983/M
    assert calc_cost("deepseek-v4-flash", 1_000_000, 0) == pytest.approx(0.0983)


def test_calc_cost_deepseek_output_only():
    # 1M output tokens at $0.1966/M
    assert calc_cost("deepseek-v4-flash", 0, 1_000_000) == pytest.approx(0.1966)


def test_calc_cost_deepseek_cache_read_uses_absolute_override():
    # in_tok includes the cached tokens (OpenRouter convention); the 1M cached
    # tokens are billed at $0.0028/M, not the generic 10%-of-input rate.
    cost = calc_cost("deepseek-v4-flash", 1_000_000, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.0028)


def test_calc_cost_anthropic_cache_read_unchanged():
    # Regression: Anthropic models keep the 0.1x-input cache-read convention.
    cost = calc_cost("claude-opus-4-6", 1_000_000, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(4.7 * 0.1)


# --- DeepSeek V4 Pro tests ---

def test_resolve_provider_deepseek_v4_pro():
    provider, model_id = resolve_provider("deepseek-v4-pro")
    assert provider == "openrouter"
    assert model_id == "deepseek/deepseek-v4-pro"


def test_costs_deepseek_v4_pro():
    from bouzecode.backend.agent.providers.registry import COSTS
    assert COSTS["deepseek-v4-pro"] == (0.435, 0.87)


def test_cache_read_override_deepseek_v4_pro():
    from bouzecode.backend.agent.providers.registry import _CACHE_READ_OVERRIDE
    assert _CACHE_READ_OVERRIDE["deepseek-v4-pro"] == 0.003625


def test_calc_cost_deepseek_v4_pro_input_only():
    # 1M pure input tokens at $0.435/M
    assert calc_cost("deepseek-v4-pro", 1_000_000, 0) == pytest.approx(0.435)


def test_calc_cost_deepseek_v4_pro_output_only():
    # 1M output tokens at $0.87/M
    assert calc_cost("deepseek-v4-pro", 0, 1_000_000) == pytest.approx(0.87)


def test_calc_cost_deepseek_v4_pro_cache_read():
    # 1M cached tokens at $0.003625/M absolute override
    cost = calc_cost("deepseek-v4-pro", 1_000_000, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.003625)
