# [desc] Tests provider routing and DeepSeek/OpenRouter cost calculation in the registry. [/desc]
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
    # Convention de la chaîne (registry.calc_cost) : in_tok EXCLUT la lecture de cache.
    # 1M tokens lus en cache, facturés $0.0028/M et non au 10 % générique de l'entrée.
    cost = calc_cost("deepseek-v4-flash", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.0028)


def test_calc_cost_anthropic_cache_read_unchanged():
    # Regression: Anthropic models keep the 0.1x-input cache-read convention.
    cost = calc_cost("claude-opus-4-6", 0, 0, cache_read_tok=1_000_000)
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
    cost = calc_cost("deepseek-v4-pro", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.003625)


# --- Muse Spark 1.3 tests (meta/muse-spark-1.3, $1.25/M in, $4.25/M out) ---

def test_resolve_provider_muse_spark_1_3_bare_name():
    provider, model_id = resolve_provider("muse-spark-1.3")
    assert provider == "openrouter"
    assert model_id == "meta/muse-spark-1.3"


def test_resolve_provider_muse_spark_1_3_contributor_bare_name():
    provider, model_id = resolve_provider("muse-spark-1.3-contributor")
    assert provider == "openrouter"
    assert model_id == "meta/muse-spark-1.3-contributor"


def test_resolve_provider_muse_spark_short_alias():
    # "muse-spark" is the convenience alias for the standard 1.3 tier.
    provider, model_id = resolve_provider("muse-spark")
    assert provider == "openrouter"
    assert model_id == "meta/muse-spark-1.3"


def test_resolve_provider_muse_spark_full_slug_kept_verbatim():
    # An explicit "meta/..." slug has no matching provider entry -> openrouter,
    # forwarded unchanged.
    provider, model_id = resolve_provider("meta/muse-spark-1.3")
    assert provider == "openrouter"
    assert model_id == "meta/muse-spark-1.3"


def test_muse_spark_1_3_listed_on_openrouter_provider():
    from bouzecode.backend.agent.providers.registry import PROVIDERS
    models = PROVIDERS["openrouter"]["models"]
    assert "muse-spark-1.3" in models
    assert "muse-spark-1.3-contributor" in models


def test_costs_muse_spark_1_3():
    from bouzecode.backend.agent.providers.registry import COSTS
    assert COSTS["muse-spark-1.3"] == (1.25, 4.25)
    assert COSTS["muse-spark-1.3-contributor"] == (0.10, 0.20)


def test_muse_spark_1_3_is_priced():
    from bouzecode.backend.agent.providers.registry import is_priced
    assert is_priced("muse-spark-1.3") is True
    assert is_priced("muse-spark-1.3-contributor") is True


def test_calc_cost_muse_spark_1_3_input_only():
    assert calc_cost("muse-spark-1.3", 1_000_000, 0) == pytest.approx(1.25)


def test_calc_cost_muse_spark_1_3_output_only():
    assert calc_cost("muse-spark-1.3", 0, 1_000_000) == pytest.approx(4.25)


def test_calc_cost_muse_spark_1_3_contributor_input_and_output():
    assert calc_cost("muse-spark-1.3-contributor", 1_000_000, 0) == pytest.approx(0.10)
    assert calc_cost("muse-spark-1.3-contributor", 0, 1_000_000) == pytest.approx(0.20)


def test_calc_cost_muse_spark_1_3_cache_read_uses_absolute_override():
    # Published cache read is $0.15/M, NOT 0.1x input ($0.125/M): the absolute
    # override must win over the generic convention.
    cost = calc_cost("muse-spark-1.3", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.15)


def test_calc_cost_muse_spark_1_3_contributor_cache_read_uses_absolute_override():
    # Contributor cache read is $0.002/M, 5x cheaper than the 0.1x convention
    # would charge ($0.01/M).
    cost = calc_cost("muse-spark-1.3-contributor", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.002)


# --- Kimi K3 tests (moonshotai/kimi-k3, $3/M in, $15/M out) ---

def test_resolve_provider_kimi_k3():
    provider, model_id = resolve_provider("kimi-k3")
    assert provider == "openrouter"
    assert model_id == "moonshotai/kimi-k3"


def test_costs_kimi_k3():
    from bouzecode.backend.agent.providers.registry import COSTS
    assert COSTS["kimi-k3"] == (3.0, 15.0)


def test_calc_cost_kimi_k3_input_only():
    # 1M pure input tokens at $3.0/M
    assert calc_cost("kimi-k3", 1_000_000, 0) == pytest.approx(3.0)


def test_calc_cost_kimi_k3_output_only():
    # 1M output tokens at $15.0/M
    assert calc_cost("kimi-k3", 0, 1_000_000) == pytest.approx(15.0)


def test_calc_cost_kimi_k3_cache_read_uses_generic_fallback():
    # No absolute cache-read override for kimi-k3: falls back to the generic
    # 0.1x-input convention ($3.0 * 0.1 = $0.30/M for the cached tokens).
    cost = calc_cost("kimi-k3", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(3.0 * 0.1)


# --- GPT-6 Astra tests (openai/gpt-6-astra, $10/M in, $50/M out) ---

def test_resolve_provider_gpt_6_alias():
    # The short name a user types resolves through _MODEL_ALIASES then
    # _OPENROUTER_MODELS: "gpt-6" -> "gpt-6-astra" -> "openai/gpt-6-astra".
    provider, model_id = resolve_provider("gpt-6")
    assert provider == "openrouter"
    assert model_id == "openai/gpt-6-astra"


def test_resolve_provider_gpt_6_astra_bare():
    provider, model_id = resolve_provider("gpt-6-astra")
    assert provider == "openrouter"
    assert model_id == "openai/gpt-6-astra"


def test_resolve_provider_gpt_6_astra_pro_bare():
    provider, model_id = resolve_provider("gpt-6-astra-pro")
    assert provider == "openrouter"
    assert model_id == "openai/gpt-6-astra-pro"


def test_resolve_provider_gpt_6_astra_full_slug():
    # An explicit vendor slug with an unknown prefix goes to OpenRouter verbatim.
    provider, model_id = resolve_provider("openai/gpt-6-astra")
    assert provider == "openrouter"
    assert model_id == "openai/gpt-6-astra"


def test_gpt_6_astra_listed_on_openrouter_provider():
    from bouzecode.backend.agent.providers.registry import PROVIDERS
    models = PROVIDERS["openrouter"]["models"]
    assert "gpt-6-astra" in models
    assert "gpt-6-astra-pro" in models


def test_costs_gpt_6_astra():
    from bouzecode.backend.agent.providers.registry import COSTS
    assert COSTS["gpt-6-astra"] == (10.0, 50.0)
    assert COSTS["gpt-6-astra-pro"] == (10.0, 50.0)


def test_gpt_6_astra_is_priced():
    from bouzecode.backend.agent.providers.registry import is_priced
    assert is_priced("gpt-6-astra") is True
    assert is_priced("gpt-6-astra-pro") is True


def test_calc_cost_gpt_6_astra_input_only():
    # 1M pure input tokens at $10.0/M
    assert calc_cost("gpt-6-astra", 1_000_000, 0) == pytest.approx(10.0)


def test_calc_cost_gpt_6_astra_output_only():
    # 1M output tokens at $50.0/M
    assert calc_cost("gpt-6-astra", 0, 1_000_000) == pytest.approx(50.0)


def test_calc_cost_gpt_6_astra_cache_read_matches_published_rate():
    # OpenRouter publishes $1/M for cached input on gpt-6-astra, which is exactly
    # the generic 0.1x-input fallback ($10.0 * 0.1) -> no override needed.
    # calc_cost bills cache_read_tok IN ADDITION to in_tok (it does not subtract the
    # cached tokens from in_tok), so pass in_tok=0 to isolate the cache-read rate.
    cost = calc_cost("gpt-6-astra", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(1.0)


# --- DeepSeek V4.1 Flash tests (deepseek/deepseek-v4.1-flash, $0.10/M in,
# --- $0.80/M out, published flat cache read $0.10/M) ---

def test_resolve_provider_deepseek_v4_1_flash_bare():
    provider, model_id = resolve_provider("deepseek-v4.1-flash")
    assert provider == "openrouter"
    assert model_id == "deepseek/deepseek-v4.1-flash"


def test_resolve_provider_deepseek_v4_1_flash_full_slug():
    # An explicit vendor slug is forwarded to OpenRouter verbatim.
    provider, model_id = resolve_provider("deepseek/deepseek-v4.1-flash")
    assert provider == "openrouter"
    assert model_id == "deepseek/deepseek-v4.1-flash"


def test_deepseek_v4_1_flash_does_not_shadow_v4_flash():
    # Regression: the older V4 Flash keeps its own slug, the dotted version is
    # a distinct model (different backbone, different pricing).
    assert resolve_provider("deepseek-v4-flash")[1] == "deepseek/deepseek-v4-flash"
    assert resolve_provider("deepseek-v4.1-flash")[1] == "deepseek/deepseek-v4.1-flash"


def test_deepseek_v4_1_flash_listed_on_openrouter_provider():
    from bouzecode.backend.agent.providers.registry import PROVIDERS
    assert "deepseek-v4.1-flash" in PROVIDERS["openrouter"]["models"]


def test_costs_deepseek_v4_1_flash():
    from bouzecode.backend.agent.providers.registry import COSTS
    assert COSTS["deepseek-v4.1-flash"] == (0.10, 0.80)


def test_deepseek_v4_1_flash_is_priced():
    from bouzecode.backend.agent.providers.registry import is_priced
    assert is_priced("deepseek-v4.1-flash") is True


def test_calc_cost_deepseek_v4_1_flash_input_only():
    assert calc_cost("deepseek-v4.1-flash", 1_000_000, 0) == pytest.approx(0.10)


def test_calc_cost_deepseek_v4_1_flash_output_only():
    assert calc_cost("deepseek-v4.1-flash", 0, 1_000_000) == pytest.approx(0.80)


def test_calc_cost_deepseek_v4_1_flash_cache_read_uses_absolute_override():
    # OpenRouter publishes a flat $0.10/M cache read, 10x the generic
    # 0.1x-input fallback ($0.01/M): the absolute override must win, otherwise
    # cached tokens would be under-billed by a factor of 10.
    cost = calc_cost("deepseek-v4.1-flash", 0, 0, cache_read_tok=1_000_000)
    assert cost == pytest.approx(0.10)


def test_cache_read_override_deepseek_v4_1_flash():
    from bouzecode.backend.agent.providers.registry import _CACHE_READ_OVERRIDE
    assert _CACHE_READ_OVERRIDE["deepseek-v4.1-flash"] == 0.10
