# [desc] Multi-provider registry: model->provider routing, API keys, costs, retry settings (Anthropic socle + OpenRouter). [/desc]
from __future__ import annotations
import os

_RATE_LIMIT_RETRY_INTERVAL_S = 3.0
_RATE_LIMIT_RETRY_BUDGET_S = 300.0
_CONNECTION_RETRY_MAX_ATTEMPTS = 10
_CONNECTION_RETRY_BASE_S = 1.0
_CONNECTION_RETRY_MAX_DELAY_S = 60.0

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "type":       "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        # The SNCF socle URL is supplied at runtime via the ANTHROPIC_BASE_URL env
        # var (set by the bouzecode wrapper); never hardcode it here.
        "base_url":   os.environ.get("ANTHROPIC_BASE_URL"),
        "context_limit": 200000,
        "models": [
            "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001",
            "claude-opus-4-5", "claude-sonnet-4-5",
            "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
        ],
    },
    "openrouter": {
        "type":       "openrouter",
        "api_key_env": "OPENROUTER_KEY",
        "base_url":   OPENROUTER_BASE_URL,
        "context_limit": 128000,
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
    },
}

# Bare model name (as the user types it) -> OpenRouter API slug.
_OPENROUTER_MODELS: dict[str, str] = {
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro":   "deepseek/deepseek-v4-pro",
}

# Flat list of the Anthropic (socle) Claude models — the primary model registry.
MODELS = list(PROVIDERS["anthropic"]["models"])

COSTS = {
    "claude-opus-4-6":          (4.7,  23.33),
    "claude-opus-4-5":          (4.7,  23.33),
    "claude-sonnet-4-6":        (2.8,  14.0),
    "claude-sonnet-4-5":        (2.8,  14.0),
    "claude-haiku-4-5-20251001": (0.8,  4.0),
    "deepseek-v4-flash":        (0.0983, 0.1966),
    "deepseek-v4-pro":          (0.435, 0.87),
}

# Absolute $/M cache-read override for providers that don't follow the Anthropic
# 0.1x-input convention (OpenRouter bills cached tokens at a flat rate, and its
# usage.prompt_tokens already includes the cached tokens).
_CACHE_READ_OVERRIDE = {
    "deepseek-v4-flash": 0.0028,
    "deepseek-v4-pro":   0.003625,
}

_MODEL_ALIASES: dict[str, str] = {
    "opus":    "claude-opus-4-6",
    "sonnet":  "claude-sonnet-4-6",
    "haiku":   "claude-haiku-4-5-20251001",
}

_PREFIXES = [
    ("claude-",       "anthropic"),
    ("opus",          "anthropic"),
    ("sonnet",        "anthropic"),
    ("haiku",         "anthropic"),
]


def resolve_provider(model: str) -> tuple[str, str]:
    """Map a user-facing model string to (provider_name, api_model_id).

    - "anthropic/claude-..." / "openrouter/..." -> explicit provider prefix, stripped.
    - "deepseek/..." (a bare slug) -> openrouter, kept verbatim.
    - "deepseek-v4-flash" -> ("openrouter", "deepseek/deepseek-v4-flash").
    - everything else (claude-*, opus/sonnet/haiku aliases) -> anthropic.
    """
    if "/" in model:
        prefix, rest = model.split("/", 1)
        if prefix in PROVIDERS:
            return prefix, rest
        return "openrouter", model
    raw = _MODEL_ALIASES.get(model, model)
    if raw in _OPENROUTER_MODELS:
        return "openrouter", _OPENROUTER_MODELS[raw]
    return "anthropic", raw


def detect_provider(model: str) -> str:
    """Provider name only — used for context limits and tool-example flavor."""
    return resolve_provider(model)[0]


def bare_model(model: str) -> str:
    raw = model.split("/", 1)[1] if "/" in model else model
    return _MODEL_ALIASES.get(raw, raw)


def model_uses_native_tools(model: str, config: dict) -> bool:
    """OpenRouter models use native (OpenAI) function-calling unless XML is forced
    via config["xml_tools"]. Anthropic always uses the XML tool protocol."""
    if config.get("xml_tools"):
        return False
    return resolve_provider(model)[0] == "openrouter"


def get_api_key(config: dict) -> str | None:
    """Anthropic API key (config override, then env). SNCF infra also accepts
    ANTHROPIC_AUTH_TOKEN."""
    cfg_key = config.get("anthropic_api_key", "")
    if cfg_key:
        return cfg_key
    for env_var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        val = os.environ.get(env_var)
        if val:
            return val
    return None


def get_openrouter_key(config: dict) -> str | None:
    cfg_key = config.get("openrouter_api_key", "")
    if cfg_key:
        return cfg_key
    for env_var in ("OPENROUTER_KEY", "OPENROUTER_API_KEY"):
        val = os.environ.get(env_var)
        if val:
            return val
    return None


def get_provider_key(provider_name: str, config: dict) -> str | None:
    """Resolve the API key for a named provider (anthropic socle or openrouter)."""
    if provider_name == "openrouter":
        return get_openrouter_key(config)
    return get_api_key(config)


def calc_cost(model: str, in_tok: int, out_tok: int,
              cache_read_tok: int = 0, cache_create_tok: int = 0) -> float:
    bm = bare_model(model)
    ic, oc = COSTS.get(bm, (0.0, 0.0))
    pure_input = max(0, in_tok - cache_read_tok - cache_create_tok)
    normal_cost = pure_input * ic
    if bm in _CACHE_READ_OVERRIDE:
        cache_read_cost = cache_read_tok * _CACHE_READ_OVERRIDE[bm]
    else:
        cache_read_cost = cache_read_tok * ic * 0.1
    cache_create_cost = cache_create_tok * ic * 1.25
    output_cost = out_tok * oc
    return (normal_cost + cache_read_cost + cache_create_cost + output_cost) / 1_000_000
