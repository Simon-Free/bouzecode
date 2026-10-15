# [desc] Multi-provider registry: model->provider routing, API keys, costs, retry settings (Anthropic gateway + OpenRouter). [/desc]
from __future__ import annotations
import os
import re

_RATE_LIMIT_RETRY_INTERVAL_S = 3.0
_RATE_LIMIT_RETRY_BUDGET_S = 300.0
_CONNECTION_RETRY_MAX_ATTEMPTS = 10
_CONNECTION_RETRY_BASE_S = 1.0
_CONNECTION_RETRY_MAX_DELAY_S = 60.0

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Generic OpenAI-compatible LLM gateway (no default URL: configure via env).
GATEWAY_PROVIDER = "gateway_openai"
ENV_GATEWAY_BASE_URL = "BOUZECODE_GATEWAY_BASE_URL"
ENV_GATEWAY_API_KEY = "BOUZECODE_GATEWAY_API_KEY"
ENV_GATEWAY_MODELS = "BOUZECODE_GATEWAY_MODELS"

PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "type":       "anthropic",
        "label":      "Anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        # Every env var accepted as this provider's key, in lookup order (get_api_key),
        # and the env var holding its URL: the single source read by the key getters
        # below and by the web server's sanity probe (web_v2/api_probe).
        "key_envs":   ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        "base_url_env": "ANTHROPIC_BASE_URL",
        # The internal LLM gateway URL is supplied at runtime via the ANTHROPIC_BASE_URL env
        # var (set by the bouzecode wrapper); never hardcode it here.
        "base_url":   os.environ.get("ANTHROPIC_BASE_URL"),
        "context_limit": 200000,
        "models": [
            # Requalified 2026-08-20 by probing the prod gateway directly: GET
            # /models lists claude-opus-5 and claude-sonnet-5, and POST
            # /v1/messages streams native tool_use for both (tool_use block +
            # input_json_delta with valid JSON + stop_reason="tool_use", zero
            # SSE errors). They were previously routed to gateway_preprod as
            # "preview" models; that was a stale leftover, not a constraint.
            # See docs/investigations/gateway_native_tool_use_retest.md.
            "claude-opus-5", "claude-sonnet-5",
            "claude-opus-4-8", "claude-opus-4-6", "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5", "claude-sonnet-4-5",
            "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
        ],
    },
    "openrouter": {
        "type":       "openrouter",
        "label":      "OpenRouter",
        "api_key_env": "OPENROUTER_KEY",
        "key_envs":   ("OPENROUTER_KEY", "OPENROUTER_API_KEY"),
        "base_url_env": None,  # public constant URL
        "base_url":   OPENROUTER_BASE_URL,
        "context_limit": 128000,
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4.1-flash", "kimi-k2.7-code", "kimi-k3", "glm-5.2", "glm-5.3-flash", "gpt-6-astra", "gpt-6-astra-pro", "muse-spark-1.3", "muse-spark-1.3-contributor", "mimo-v2.6-pro"],
    },
    # internal LLM gateway PREPROD: an OpenAI-compatible LiteLLM proxy. We route here the
    # models the prod gateway does not serve (gpt-5.5, mistral, gemini). It is an
    # internal endpoint reached directly (no NTLM proxy), unlike OpenRouter.
    # Do NOT park a Claude model here by default: when the prod gateway serves it,
    # the "anthropic" provider gives native tool_use, cache_control and the
    # httpx mid-stream retry (see the 2026-08-20 requalification above).
    # base_url is supplied at runtime via PREPROD_ENDPOINT (never hardcoded);
    # auth uses the user env var OPENAI_API_KEY_PP.
    "gateway_preprod": {
        "type":       "openai",
        "label":      "gateway préprod",
        "api_key_env": "OPENAI_API_KEY_PP",
        "key_envs":   ("OPENAI_API_KEY_PP",),
        "base_url_env": "PREPROD_ENDPOINT",
        "base_url":   os.environ.get("PREPROD_ENDPOINT"),
        "context_limit": 128000,
        "models": [
            "gpt-5.5", "gpt-5.5-2026-04-24",
            "mistral-medium-3-5",
            "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-embedding-2",
            # Exception to the rule above (2026-10-05, explicit user request):
            # claude-opus-5-5 and claude-sonnet-5-5 are served by the PREPROD gateway
            # only (GET /v1/models, 2026-10-05). Move them to the "anthropic"
            # provider as soon as the prod gateway serves them.
            "claude-opus-5-5", "claude-sonnet-5-5",
        ],
    },
    # internal LLM gateway PROD models that are OpenAI-compatible (gpt-5.6-*). The prod gateway
    # only serves these on /v1/chat/completions; its Anthropic pass-through crashes
    # in streaming, so we route them through the OpenAI transport (like gateway_preprod) but
    # pointed at the PROD endpoint (ANTHROPIC_BASE_URL) with the prod auth token
    # (ANTHROPIC_AUTH_TOKEN, via get_api_key). Reached directly (no NTLM proxy).
    "gateway_openai": {
        "type":       "openai",
        "label":      "gateway prod (OpenAI)",
        "api_key_env": "ANTHROPIC_AUTH_TOKEN",
        # Same auth as the anthropic gateway (get_provider_key -> get_api_key).
        "key_envs":   ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        "base_url_env": "ANTHROPIC_BASE_URL",
        "base_url":   os.environ.get("ANTHROPIC_BASE_URL"),
        "context_limit": 200000,
        "models": [
            "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra",
        ],
    },
}

# Bare model name (as the user types it) -> OpenRouter API slug.
_OPENROUTER_MODELS: dict[str, str] = {
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro":   "deepseek/deepseek-v4-pro",
    "deepseek-v4.1-flash": "deepseek/deepseek-v4.1-flash",
    "kimi-k2.7-code":    "moonshotai/kimi-k2.7-code",
    "kimi-k3":           "moonshotai/kimi-k3",
    "glm-5.2":           "z-ai/glm-5.2",
    "glm-5.3-flash":     "z-ai/glm-5.3-flash",
    "gpt-6-astra":       "openai/gpt-6-astra",
    "gpt-6-astra-pro":   "openai/gpt-6-astra-pro",
    "muse-spark-1.3":             "meta/muse-spark-1.3",
    "muse-spark-1.3-contributor": "meta/muse-spark-1.3-contributor",
    "mimo-v2.6-pro":              "xiaomi/mimo-v2.6-pro",
}

# Preprod-only gateway models routed to the "gateway_preprod" provider. The API model id
# is the bare name verbatim (the LiteLLM proxy expects exactly these strings).
_GATEWAY_PREPROD_MODELS: set[str] = set(PROVIDERS["gateway_preprod"]["models"])

# Prod gateway models that are OpenAI-compatible, NOT Anthropic-compatible. The prod
# gateway serves gpt-5.6-* only on /v1/chat/completions (OpenAI). Its Anthropic
# pass-through (/v1/messages) crashes in streaming (LiteLLM IndexError on
# chunk.choices[0].finish_reason), yielding an empty reply. So we must route these
# through the OpenAI transport pointed at the prod gateway, NOT the anthropic fallback.
_GATEWAY_OPENAI_MODELS: set[str] = set(PROVIDERS["gateway_openai"]["models"])

# Flat list of the Anthropic (gateway) Claude models — the primary model registry.
MODELS = list(PROVIDERS["anthropic"]["models"])

COSTS = {
    "claude-opus-4-8":          (4.7,  23.33),
    "claude-opus-4-6":          (4.7,  23.33),
    "claude-opus-4-5":          (4.7,  23.33),
    "claude-opus-5":            (4.7,  23.33),
    # Preprod gateway: no published tariff yet, billed like the other opus on the
    # gateway so budget tracking stays meaningful instead of is_priced() == False.
    "claude-opus-5-5":          (4.7,  23.33),
    # Preprod gateway: Anthropic list price of Claude Sonnet 5.5 ($2/M in, $10/M out),
    # not the gateway-scaled grid of the entries around it (sonnet-5: 2.8 vs $3 list).
    "claude-sonnet-5-5":        (2.0,  10.0),
    "claude-sonnet-5":          (2.8,  14.0),
    "claude-sonnet-4-6":        (2.8,  14.0),
    "claude-sonnet-4-5":        (2.8,  14.0),
    "claude-haiku-4-5-20251001": (0.8,  4.0),
    "deepseek-v4-flash":        (0.0983, 0.1966),
    "deepseek-v4-pro":          (0.435, 0.87),
    # DeepSeek V4.1 Flash (deepseek/deepseek-v4.1-flash, published 2026-09-10):
    # input $0.10/M, output $0.80/M, flat cache read $0.10/M (see override below).
    "deepseek-v4.1-flash":      (0.10, 0.80),
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
    # Z.ai GLM 5.3 Flash (z-ai/glm-5.3-flash): input $0.075/M, output $0.25/M.
    # Read straight off GET openrouter.ai/api/v1/models on 2026-08-27 (reachable
    # through the local px relay on 127.0.0.1:3128). Upstream advertises a
    # 1_310_720-token context, far above the 128k the openrouter provider entry
    # declares. No published cache-read rate -> 0.1x-input convention applies.
    "glm-5.3-flash":            (0.075, 0.25),
    # OpenAI GPT-6 Astra (openai/gpt-6-astra): input $10/M, output $50/M.
    # Read straight off GET openrouter.ai/api/v1/models on 2026-09-07 (through the
    # local px relay on 127.0.0.1:3128). "-pro" is the same underlying model served
    # with reasoning.mode=pro and carries an identical price grid.
    # Upstream advertises a 1_050_000-token context, far above the 128k the
    # openrouter provider entry declares (same situation as glm-5.3-flash).
    # Published cache-read rate is $1/M, which is exactly 0.1x input -> the generic
    # 0.1x-input convention already yields the right number, so no
    # _CACHE_READ_OVERRIDE entry is needed here.
    "gpt-6-astra":              (10.0, 50.0),
    "gpt-6-astra-pro":          (10.0, 50.0),
    # Meta Muse Spark 1.3 (meta/muse-spark-1.3): input $1.25/M, output $4.25/M.
    # Read straight off GET openrouter.ai/api/v1/models on 2026-09-07 (through the
    # local px relay on 127.0.0.1:3128) and cross-checked on the model page.
    # Upstream advertises a 1_048_576-token context, far above the 128k the
    # openrouter provider entry declares (same situation as glm-5.3-flash).
    # Cache read is billed $0.15/M -- NOT 0.1x input ($0.125/M) -- so it needs an
    # explicit _CACHE_READ_OVERRIDE entry below.
    "muse-spark-1.3":             (1.25, 4.25),
    # Muse Spark 1.3 Contributor: the cost-efficient tier of the same model family,
    # input $0.10/M, output $0.20/M, same 1M context. Its cache read is $0.002/M,
    # i.e. 5x CHEAPER than the 0.1x-input convention would charge ($0.01/M), hence
    # the _CACHE_READ_OVERRIDE entry below.
    "muse-spark-1.3-contributor": (0.10, 0.20),
    # Xiaomi MiMo V2.6 Pro (xiaomi/mimo-v2.6-pro): input $0.435/M, output $0.87/M, lu sur
    # GET openrouter.ai/api/v1/models/xiaomi/mimo-v2.6-pro/endpoints le 24/09 (xiaomi/fp8 et
    # deepinfra/fp8, même grille). Contexte amont 1 048 576 ; on garde les 128 k du fournisseur
    # comme pour les autres modèles à 1 M. Lecture de cache $0.0036/M, soit ≈ 0.008x l'entrée
    # (et non 0.1x) -> entrée _CACHE_READ_OVERRIDE ci-dessous.
    "mimo-v2.6-pro":              (0.435, 0.87),
}

# Absolute $/M cache-read override for providers that don't follow the Anthropic
# 0.1x-input convention (OpenRouter bills cached tokens at a flat rate, and its
# usage.prompt_tokens already includes the cached tokens).
_CACHE_READ_OVERRIDE = {
    "deepseek-v4-flash": 0.0028,
    "deepseek-v4-pro":   0.003625,
    # Published flat cache read, 10x the 0.1x-input convention ($0.01) -> override.
    "deepseek-v4.1-flash": 0.10,
    "kimi-k2.7-code":    0.19,
    # Published flat cache-read rates (2026-09-07), both off the 0.1x convention.
    "muse-spark-1.3":             0.15,
    "muse-spark-1.3-contributor": 0.002,
    "mimo-v2.6-pro":              0.0036,
}

_MODEL_ALIASES: dict[str, str] = {
    "opus":    "claude-opus-5",
    "sonnet":  "claude-sonnet-5",
    "haiku":   "claude-haiku-4-5-20251001",
    "gpt-6":   "gpt-6-astra",
    "muse-spark": "muse-spark-1.3",
}

# Repli côté client sur REFUS (`content_filter` / `refusal`) : chaîne de repli à plusieurs
# marches (agent/refusal_fallback.py). Chaque entrée donne la marche SUIVANTE d'un modèle ;
# la chaîne d'un modèle suit ces liens : claude-opus-5-5 -> claude-sonnet-5-5 ->
# claude-opus-5. Un tour refusé est rejoué sur la marche suivante, une tentative par marche
# et par tour au plus ; le repli collant (agent/repli_collant.py) se colle à la dernière
# marche qui a répondu. Mesuré le 2026-10-06 (session b2feb0ff, payload exact rejoué) :
# claude-opus-5-5 12/12 refus, claude-opus-5 0/6, claude-sonnet-5-5 1/6. Remesuré le
# 2026-10-08 (session 4b47c33d, tour 25, 12 rejeux) : claude-opus-5-5 2 à 9/12,
# claude-sonnet-5-5 0/12, claude-opus-5 0/12. Session 28738fd0 (2026-10-12) : sonnet-5-5,
# collé après un refus d'opus-5-5, a refusé à son tour aux tours 11 et 12 — d'où la
# seconde marche claude-opus-5 (gateway PROD, résolu en "anthropic"). La doc Anthropic
# d'Opus 5.5 donne le repli de modèle comme seul remède ; les `fallbacks` serveur sont
# indisponibles derrière LiteLLM. Surcharge : config["refusal_fallback"] puis env
# BOUZECODE_REFUSAL_FALLBACK (un modèle, ou une chaîne « a,b », `none` coupe).
REFUSAL_FALLBACK: dict[str, str] = {
    "claude-opus-5-5": "claude-sonnet-5-5",
    "claude-sonnet-5-5": "claude-opus-5",
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
    if raw in _GATEWAY_PREPROD_MODELS:
        return "gateway_preprod", raw
    if raw in _GATEWAY_OPENAI_MODELS:
        return "gateway_openai", raw
    return "anthropic", raw


# liste blanche des fournisseurs pour un process hébergé.
# `BOUZECODE_ALLOWED_PROVIDERS=anthropic,gateway_openai` refuse tout autre fournisseur (en
# particulier `openrouter`, qui envoie le contexte hors du gateway). Absente : aucun filtre.
ALLOWED_PROVIDERS_ENV = "BOUZECODE_ALLOWED_PROVIDERS"


class ProviderNotAllowed(RuntimeError):
    """Fournisseur hors de la liste blanche BOUZECODE_ALLOWED_PROVIDERS."""


def allowed_providers() -> frozenset | None:
    raw = os.environ.get(ALLOWED_PROVIDERS_ENV)
    if raw is None or not raw.strip():
        return None
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def check_provider_allowed(provider_name: str, model: str = "") -> None:
    """Lève ProviderNotAllowed si la liste blanche est posée et n'inclut pas ce fournisseur."""
    allowed = allowed_providers()
    if allowed is None or provider_name in allowed:
        return
    raise ProviderNotAllowed(
        f"Fournisseur « {provider_name} » refusé pour le modèle « {model} » : "
        f"{ALLOWED_PROVIDERS_ENV}={','.join(sorted(allowed))}. Choisir un modèle servi par "
        "un fournisseur autorisé.")


def detect_provider(model: str) -> str:
    """Provider name only — used for context limits and tool-example flavor."""
    return resolve_provider(model)[0]


_CLAUDE_DOTTED_VERSION = re.compile(r"(claude-[a-z]+-\d+)\.(\d+)")


def bare_model(model: str) -> str:
    """Bare id used for lookups; OpenRouter's 'claude-opus-5.5' becomes 'claude-opus-5-5'."""
    raw = model.split("/", 1)[1] if "/" in model else model
    raw = _MODEL_ALIASES.get(raw, raw)
    return _CLAUDE_DOTTED_VERSION.sub(r"\1-\2", raw)


# Anthropic endpoints measured to serve well-formed native tool_use SSE blocks.
# The gateway entry is backed by docs/investigations/gateway_native_tool_use_retest.md
# (2026-07-27, 6/6 requests clean); api.anthropic.com is the reference API itself.
_NATIVE_TOOL_ENDPOINTS = ("api.anthropic.com", "llm-gateway.example.com")

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
    from .llm_proxy import is_llm_proxy

    # The demo LLM proxy relays the gateway unchanged: same SSE stream as the gateway.
    return is_llm_proxy(base_url) or any(host in base_url for host in _NATIVE_TOOL_ENDPOINTS)


def model_uses_native_tools(model: str, config: dict) -> bool:
    """OpenAI-compatible providers (OpenRouter, gateway preprod) use native function
    calling. Anthropic follows BOUZECODE_ANTHROPIC_NATIVE_TOOLS ("1" native, "0" XML),
    and otherwise the default policy above. config["xml_tools"] outranks everything.
    """
    if config.get("xml_tools"):
        return False
    provider = resolve_provider(model)[0]
    if provider in ("openrouter", "gateway_preprod"):
        return True
    if provider != "anthropic":
        return False
    switch = os.environ.get("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "")
    if switch in ("0", "1"):
        return switch == "1"  # an explicit choice is absolute, endpoint notwithstanding
    base_url = os.environ.get("ANTHROPIC_BASE_URL") or PROVIDERS["anthropic"].get("base_url")
    return _NATIVE_TOOLS_DEFAULT_ON and anthropic_endpoint_serves_native_tools(base_url)


# CONVENTION UNIQUE DES COMPTEURS D'ENTRÉE, dans toute la chaîne (AssistantTurn, totaux de
# session, compaction_log, /turns, /costs, calc_cost) :
#   in_tokens = prompt NON lu en cache = frais + ÉCRIT au cache ; cache_read à part.
# C'est ce que renvoie le internal LLM gateway (mesuré : input 55 471 = cache_create 55 200 + wire,
# cf. docs/archive/RAPPORT_VERIF_CACHE_NOTES_BLOCK.md), donc ce que contiennent toutes les
# sessions déjà sur disque. L'API officielle, elle, EXCLUT l'écriture de cache de
# `input_tokens` : son flux est ramené à la convention à la lecture (anthropic_stream).
_EXCLUSIVE_INPUT_HOSTS = ("api.anthropic.com",)


def anthropic_input_includes_cache_write(base_url: str | None) -> bool:
    """Le `usage.input_tokens` de cet endpoint inclut-il déjà `cache_creation_input_tokens` ?

    Oui pour le gateway et les passerelles LiteLLM ; non pour l'API officielle (base_url None
    = api.anthropic.com). BOUZECODE_USAGE_INPUT_INCLUDES_CACHE_WRITE ("1"/"0") tranche.
    Présomption seulement : mesuré le 2026-09-29, le gateway EXCLUT l'écriture ; anthropic_stream
    l'ajoute dès que l'entrée brute est inférieure à l'écriture (inclusion alors impossible)."""
    switch = os.environ.get("BOUZECODE_USAGE_INPUT_INCLUDES_CACHE_WRITE", "")
    if switch in ("0", "1"):
        return switch == "1"
    if base_url is None:
        return False
    return not any(host in base_url for host in _EXCLUSIVE_INPUT_HOSTS)


def _env_key(provider_name: str) -> str | None:
    """First non-empty env var among PROVIDERS[provider_name]["key_envs"]."""
    for env_var in PROVIDERS[provider_name]["key_envs"]:
        val = os.environ.get(env_var)
        if val:
            return val
    return None


def get_api_key(config: dict) -> str | None:
    """Anthropic API key (config override, then env). corporate infra also accepts
    ANTHROPIC_AUTH_TOKEN."""
    return config.get("anthropic_api_key", "") or _env_key("anthropic")


def get_openrouter_key(config: dict) -> str | None:
    return config.get("openrouter_api_key", "") or _env_key("openrouter")


def get_gateway_preprod_key(config: dict) -> str | None:
    return config.get("gateway_preprod_api_key", "") or _env_key("gateway_preprod")


def get_provider_key(provider_name: str, config: dict) -> str | None:
    """Resolve the API key for a named provider (anthropic gateway, openrouter,
    or gateway preprod)."""
    if provider_name == "openrouter":
        return get_openrouter_key(config)
    if provider_name == "gateway_preprod":
        return get_gateway_preprod_key(config)
    # gateway_openai (OpenAI-compat prod gateway) uses the same auth as anthropic gateway.
    return get_api_key(config)


def is_priced(model: str) -> bool:
    """Ce modèle a-t-il un tarif connu ? Faux => `calc_cost` rend 0, ce qui DOIT se voir.

    `COSTS.get(bm, (0.0, 0.0))` fait qu'un modèle absent de la table coûte silencieusement
    zéro : les vues de coût affichaient 0 $ sans le moindre avertissement. Un tarif à
    (0.0, 0.0) explicite (GLM, en attente de confirmation) compte aussi comme non tarifé —
    c'est le même mensonge à l'écran.
    """
    ic, oc = COSTS.get(bare_model(model), (0.0, 0.0))
    return bool(ic or oc)


def fresh_input_tokens(in_tok: int, cache_create_tok: int) -> int:
    """Entree fraiche (ni lue ni ecrite en cache). Convention de la chaine : `in_tok` COMPREND
    l'ecriture de cache et EXCLUT la lecture (anthropic_stream._canonical_in,
    openrouter_stream._usage_tokens) ; on ne retire donc que l'ecriture."""
    return max(0, in_tok - cache_create_tok)


def calc_cost(model: str, in_tok: int, out_tok: int,
              cache_read_tok: int = 0, cache_create_tok: int = 0) -> float:
    bm = bare_model(model)
    ic, oc = COSTS.get(bm, (0.0, 0.0))
    # `in_tok` ne CONTIENT PAS `cache_read_tok` (l'API les compte à part) : le soustraire
    # ramenait `pure_input` à 0 sur tout tour bien caché (in=12479, cache_read=40180 =>
    # max(0, -31383) = 0), donc l'input frais était facturé zéro et le coût sous-estimé.
    # On ne retire que l'écriture de cache, qui EST comprise dans `in_tok` et qui est
    # facturée juste en dessous à son propre tarif (1.25x).
    pure_input = fresh_input_tokens(in_tok, cache_create_tok)
    normal_cost = pure_input * ic
    if bm in _CACHE_READ_OVERRIDE:
        cache_read_cost = cache_read_tok * _CACHE_READ_OVERRIDE[bm]
    else:
        cache_read_cost = cache_read_tok * ic * 0.1
    cache_create_cost = cache_create_tok * ic * 1.25
    output_cost = out_tok * oc
    return (normal_cost + cache_read_cost + cache_create_cost + output_cost) / 1_000_000
