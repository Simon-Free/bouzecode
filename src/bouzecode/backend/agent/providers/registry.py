# [desc] Multi-provider registry: model->provider routing, API keys, costs, retry settings (Anthropic, OpenRouter, optional OpenAI-compatible gateway). [/desc]
from __future__ import annotations
import os

_RATE_LIMIT_RETRY_INTERVAL_S = 3.0
_RATE_LIMIT_RETRY_BUDGET_S = 300.0
_CONNECTION_RETRY_MAX_ATTEMPTS = 10
_CONNECTION_RETRY_BASE_S = 1.0
_CONNECTION_RETRY_MAX_DELAY_S = 60.0

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Optional third provider: an OpenAI-compatible LLM gateway you run or your
# organisation runs (LiteLLM, vLLM, a corporate gateway…). Nothing about it is
# hardcoded — endpoint, key and model list all come from the environment, so the
# provider simply stays inert when the variables are unset.
GATEWAY_PROVIDER = "gateway"
ENV_GATEWAY_BASE_URL = "BOUZECODE_GATEWAY_BASE_URL"
ENV_GATEWAY_API_KEY = "BOUZECODE_GATEWAY_API_KEY"
ENV_GATEWAY_MODELS = "BOUZECODE_GATEWAY_MODELS"
ENV_NATIVE_TOOL_ENDPOINTS = "BOUZECODE_NATIVE_TOOL_ENDPOINTS"


def _env_list(env_var: str) -> list[str]:
    """Comma-separated env var -> list of trimmed, non-empty items."""
    return [item.strip() for item in os.environ.get(env_var, "").split(",") if item.strip()]


def gateway_base_url() -> str | None:
    """Base URL of the optional OpenAI-compatible gateway (env-only, no default)."""
    return os.environ.get(ENV_GATEWAY_BASE_URL)


def gateway_models() -> set[str]:
    """Models routed to the gateway, declared in BOUZECODE_GATEWAY_MODELS.

    Each name is sent verbatim as the API model id, so it must be exactly what
    the gateway expects."""
    return set(_env_list(ENV_GATEWAY_MODELS))


PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "type":       "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        # None = the official API. Point at your own Anthropic-compatible endpoint
        # with the ANTHROPIC_BASE_URL env var; never hardcode one here.
        "base_url":   os.environ.get("ANTHROPIC_BASE_URL"),
        "context_limit": 200000,
        "models": [
            "claude-opus-4-8", "claude-opus-4-6", "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5", "claude-sonnet-4-5",
            "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
        ],
    },
    "openrouter": {
        "type":       "openrouter",
        "api_key_env": "OPENROUTER_KEY",
        "base_url":   OPENROUTER_BASE_URL,
        "context_limit": 128000,
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "kimi-k2.7-code", "kimi-k3", "glm-5.2"],
    },
    GATEWAY_PROVIDER: {
        "type":       "openai",
        "api_key_env": ENV_GATEWAY_API_KEY,
        "base_url":   gateway_base_url(),
        "context_limit": 128000,
        "models":     sorted(gateway_models()),
    },
}

# Bare model name (as the user types it) -> OpenRouter API slug.
_OPENROUTER_MODELS: dict[str, str] = {
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro":   "deepseek/deepseek-v4-pro",
    "kimi-k2.7-code":    "moonshotai/kimi-k2.7-code",
    "kimi-k3":           "moonshotai/kimi-k3",
    "glm-5.2":           "z-ai/glm-5.2",
}

# Flat list of the Anthropic Claude models — the primary model registry.
MODELS = list(PROVIDERS["anthropic"]["models"])

COSTS = {
    "claude-opus-4-8":          (4.7,  23.33),
    "claude-opus-4-6":          (4.7,  23.33),
    "claude-opus-4-5":          (4.7,  23.33),
    "claude-sonnet-4-6":        (2.8,  14.0),
    "claude-sonnet-4-5":        (2.8,  14.0),
    "claude-haiku-4-5-20251001": (0.8,  4.0),
    "deepseek-v4-flash":        (0.0983, 0.1966),
    "deepseek-v4-pro":          (0.435, 0.87),
    # Moonshot Kimi K2.7-Code: cache-miss input $0.95/M, output $4.00/M
    # (cache-hit $0.19/M handled by _CACHE_READ_OVERRIDE below).
    "kimi-k2.7-code":           (0.95, 4.0),
    # Moonshot Kimi K3 (moonshotai/kimi-k3): input $3.00/M, output $15.00/M
    # (openrouter.ai/moonshotai/kimi-k3, confirmed 2026-07). No dedicated
    # cache-read rate published -> falls back to the 0.1x-input convention
    # ($0.30/M cache read); add a _CACHE_READ_OVERRIDE entry if OpenRouter
    # later exposes a flat cached rate. Note: upstream capacity limited (429s).
    "kimi-k3":                   (3.0, 15.0),
    # TODO: fill ($/M in, $/M out) from openrouter.ai/z-ai/glm-5.2 — left at 0
    # until confirmed (cost reporting shows $0 for GLM meanwhile).
    "glm-5.2":                  (0.0, 0.0),
}

# Absolute $/M cache-read override for providers that don't follow the Anthropic
# 0.1x-input convention (OpenRouter bills cached tokens at a flat rate, and its
# usage.prompt_tokens already includes the cached tokens).
_CACHE_READ_OVERRIDE = {
    "deepseek-v4-flash": 0.0028,
    "deepseek-v4-pro":   0.003625,
    "kimi-k2.7-code":    0.19,
}

_MODEL_ALIASES: dict[str, str] = {
    "opus":    "claude-opus-4-8",
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
    if raw in gateway_models():
        return GATEWAY_PROVIDER, raw
    return "anthropic", raw


def detect_provider(model: str) -> str:
    """Provider name only — used for context limits and tool-example flavor."""
    return resolve_provider(model)[0]


def bare_model(model: str) -> str:
    raw = model.split("/", 1)[1] if "/" in model else model
    return _MODEL_ALIASES.get(raw, raw)


# Anthropic endpoints measured to serve well-formed native tool_use SSE blocks:
# api.anthropic.com is the reference API itself. A proxy in front of it may mangle
# those blocks, so an endpoint has to be vouched for before it lands here — declare
# your own hosts (comma-separated) in BOUZECODE_NATIVE_TOOL_ENDPOINTS.
_NATIVE_TOOL_ENDPOINTS = ("api.anthropic.com",)


def _native_tool_endpoints() -> tuple[str, ...]:
    return _NATIVE_TOOL_ENDPOINTS + tuple(_env_list(ENV_NATIVE_TOOL_ENDPOINTS))

# Whether an Anthropic endpoint from the table above uses native tools when nothing
# is set. OFF deliberately: native is the better protocol (it deletes the whole
# XML-parsing failure class) but this is the hot path of every session, and the
# 2026-07-27 evidence covers 4 tool schemas over short exchanges, not the 22 schemas
# and long sessions production actually runs. Opt in with
# BOUZECODE_ANTHROPIC_NATIVE_TOOLS=1; promoting native to the default later is this
# one flag.
_NATIVE_TOOLS_DEFAULT_ON = False


def anthropic_endpoint_serves_native_tools(base_url: str | None) -> bool:
    """Same shape as dispatch._resolve_cache_control: branch on the endpoint, since
    what a gateway does to the SSE stream is a property of the gateway, not the model."""
    if base_url is None:
        return True  # the official API, reached without an override
    return any(host in base_url for host in _native_tool_endpoints())


def model_uses_native_tools(model: str, config: dict) -> bool:
    """OpenAI-compatible providers (OpenRouter, gateway) use native function
    calling. Anthropic follows BOUZECODE_ANTHROPIC_NATIVE_TOOLS ("1" native, "0" XML),
    and otherwise the default policy above. config["xml_tools"] outranks everything.
    """
    if config.get("xml_tools"):
        return False
    provider = resolve_provider(model)[0]
    if provider in ("openrouter", GATEWAY_PROVIDER):
        return True
    if provider != "anthropic":
        return False
    switch = os.environ.get("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "")
    if switch in ("0", "1"):
        return switch == "1"  # an explicit choice is absolute, endpoint notwithstanding
    base_url = os.environ.get("ANTHROPIC_BASE_URL") or PROVIDERS["anthropic"].get("base_url")
    return _NATIVE_TOOLS_DEFAULT_ON and anthropic_endpoint_serves_native_tools(base_url)


def get_api_key(config: dict) -> str | None:
    """Anthropic API key (config override, then env). ANTHROPIC_AUTH_TOKEN is also
    accepted — some Anthropic-compatible endpoints authenticate with it instead."""
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


def get_gateway_key(config: dict) -> str | None:
    cfg_key = config.get("gateway_api_key", "")
    if cfg_key:
        return cfg_key
    return os.environ.get(ENV_GATEWAY_API_KEY)


def get_provider_key(provider_name: str, config: dict) -> str | None:
    """Resolve the API key for a named provider (anthropic, openrouter, gateway)."""
    if provider_name == "openrouter":
        return get_openrouter_key(config)
    if provider_name == GATEWAY_PROVIDER:
        return get_gateway_key(config)
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
