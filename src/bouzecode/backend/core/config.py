# [desc] Configuration loading, saving, and defaults for multi-provider bouzecode CLI tool. [/desc]
"""Configuration management for bouzecode (multi-provider)."""
from bouzecode.paths import data_dir as bouzecode_data_dir
import os
import json
from pathlib import Path

CONFIG_DIR        = bouzecode_data_dir()
CONFIG_FILE       = CONFIG_DIR  / "config.json"
HISTORY_FILE      = CONFIG_DIR  / "input_history.txt"
SESSIONS_DIR      = CONFIG_DIR  / "sessions"
DAILY_DIR         = SESSIONS_DIR / "daily"       # daily/YYYY-MM-DD/session_*.json
SESSION_HIST_FILE = SESSIONS_DIR / "history.json" # master: all sessions ever
LOGS_DIR          = CONFIG_DIR  / "logs"

# kept for backward-compat (/resume still reads from here)
MR_SESSION_DIR = SESSIONS_DIR / "mr_sessions"

DEFAULTS = {
    # claude-opus-5-5, servi par le gateway PRÉPROD seulement (route gateway_preprod), demande
    # utilisateur du 2026-10-05. Les appels annexes suivent (side_model.modele_annexe).
    "model":            "claude-opus-5-5",
    "max_tokens":       64000,
    # Auto task-routing classifier (feature/bug profile). OFF by default: it fires
    # a tiny max_tokens=12 side-call at session start whose truncation prints an
    # alarming (and here irrelevant) banner. Set True to re-enable. --profile still
    # routes explicitly regardless of this flag.
    "task_classification": False,
    # auto | accept-all | manual. accept-all par défaut (demande utilisateur 2026-09-30) :
    # `/permissions auto` le repasse en mode questions, et ce choix enregistré reste prioritaire.
    "permission_mode":  "accept-all",
    "verbose":          False,
    "thinking":         True,
    "thinking_mode":    "extended",  # "extended" | "loud" (same API thinking, label only) | "off"
    # Niveau de thinking NATIF des modèles Claude : none | low | medium | high | xhigh | max.
    # Vide = variable BOUZECODE_THINKING, sinon "medium". Commande `/thinking <niveau>`.
    # Voir agent/providers/thinking_level.py (incident claude-opus-5 du 2026-09-29).
    "thinking_level":   "",
    "native_reasoning": False,    # OpenRouter uniquement : canal de raisonnement natif (opt-in).
    # Chien de garde de progrès du flux chat/completions (providers/backends/stream_progress.py) :
    # sans token, reasoning, tool_call ni usage pendant ce délai, la tentative est relancée.
    # Les variables BOUZECODE_STREAM_FIRST_PROGRESS_TIMEOUT_S / _PROGRESS_TIMEOUT_S priment.
    "stream_first_progress_timeout_s": 120,
    "stream_progress_timeout_s":       90,
    "custom_base_url":  "",       # for "custom" provider
    "max_tool_output":  32000,
    # Rattrapage d'un Methodology oublié (rapport docs/reduction_tokens §2.2) :
    #   "llm"       : appel annexe forcé qui relit la note + la réflexion du tour (jusqu'à
    #                 124 k tokens par rattrapage) et rédige la note manquante ;
    #   "mecanique" : le harnais écrit lui-même une ligne « (note non écrite par le modèle) —
    #                 outils : Edit app.js, Bash pytest… », sans appel LLM.
    # A/B DeepSeek du 24/09 (docs/reduction_tokens/correctifs.md) : réussite et taux d'oubli
    # égaux, 0 token de rattrapage au lieu de ≈ 3 300 par oubli, coût −18 % → "mecanique".
    "methodology_recovery": "mecanique",
    # Modèle des appels ImageQuestion. Vide = le modèle de la session. À poser si le modèle
    # de session ne voit pas les images (ex. "deepseek-v4.1-flash" ou "qwen/qwen3-vl-8b-instruct").
    "vision_model":     "",
    # Fournisseur OpenRouter épinglé par modèle (docs/reduction_tokens/correctifs.md) : requête
    # sur le 1er (ou celui qui sert déjà la session), reprises sur lui, repli sur la liste
    # seulement ensuite, puis la session reste sur le fournisseur de repli. {} = routage libre.
    # Mesuré le 24/09 : deepinfra/fp8 (cache dès le 2e appel, 0,14/0,0042/0,42 $/M), wafer,
    # streamlake/fp8 ; exclus : morph (jamais de cache), fireworks (429), DeepSeek (404).
    "openrouter_provider": {
        "deepseek-v4.1-flash": ["deepinfra/fp8", "wafer", "streamlake/fp8"],
        # Mesuré le 24/09 (3 appels, préfixe ≈ 6 900 tokens) : xiaomi/fp8 cache dès le 2e appel
        # (6 784 lus), 1er token 2-5 s, 34-45 tok/s ; deepinfra/fp8 ne cache qu'au 3e appel,
        # 21 tok/s, un 1er token à 53 s → repli seulement.
        "mimo-v2.6-pro": ["xiaomi/fp8", "deepinfra/fp8"],
    },
    # Overflow budget is dynamic: limit_chars = max(floor, X/cache_div + Y/fresh_div)
    # in tokens, then *chars_per_token, capped at the max. X = context re-read on a
    # retry (cache + fresh input of the last turn), Y = that turn's fresh input. The
    # divisors come from the price ratios (cache-read 0.1x in, output 5x in => X/50,
    # Y/5): a pricier context to re-process earns proportionally more thinking before
    # we pay the cut+retry tax. See thinking_summary.py / loop_turn.py.
    # 0 = désactivé (choix utilisateur 2026-09-24 : laisser le modèle réfléchir jusqu'au bout ;
    # la réflexion reste bornée par max_tokens). Mettre un nombre de caractères pour réactiver.
    "thinking_overflow_limit": 0,  # chars — MINIMUM (floor); 0 disables overflow
    "thinking_overflow_max":   80000,  # chars — ceiling (anti-runaway)
    "thinking_cache_divisor":  50,     # cached tokens (X) -> thinking tokens allowed
    "thinking_fresh_divisor":  5,      # fresh tokens (Y) -> thinking tokens allowed
    "thinking_chars_per_token": 4,     # tokens -> chars conversion (FR + code mix)
    "max_agent_depth":  4,  # profondeur max des sous-agents (multi_agent/profondeur.py)
    "subagents_window": False,  # TUI : True = un sous-agent par fenêtre de terminal (ancien mode), False = en process + barre du bas
    "max_concurrent_agents": 3,
    "database_kind":         "rec",  # demodb environment (dev/rec/pp/prod/local)
    "gitlab_url":            "https://gitlab.example.com",
    "gitlab_group_id":       "",     # numeric ID of the GitLab group to explore
}


def load_config() -> dict:
    CONFIG_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    # Backward-compat: legacy single api_key → anthropic_api_key
    if cfg.get("api_key") and not cfg.get("anthropic_api_key"):
        cfg["anthropic_api_key"] = cfg.pop("api_key")
    # Also accept ANTHROPIC_API_KEY env for backward-compat
    if not cfg.get("anthropic_api_key"):
        cfg["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    return cfg


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    # Strip internal runtime keys (e.g. _run_query_callback) before saving
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def current_provider(cfg: dict) -> str:
    from ..agent.providers import detect_provider
    return detect_provider(cfg.get("model", DEFAULTS["model"]))


def has_api_key(cfg: dict) -> bool:
    """Check whether the active provider has an API key configured."""
    from ..agent.providers.registry import get_provider_key
    pname = current_provider(cfg)
    key = get_provider_key(pname, cfg)
    return bool(key)


def missing_key_hint(cfg: dict) -> str:
    """Warning shown when the active provider has no key: names the env vars
    of THAT provider (gateway_preprod reads OPENAI_API_KEY_PP, not ANTHROPIC_API_KEY)."""
    from ..agent.providers.registry import PROVIDERS
    pname = current_provider(cfg)
    envs = PROVIDERS.get(pname, {}).get("key_envs") or ("ANTHROPIC_API_KEY",)
    cfg_key = "anthropic_api_key" if pname in ("anthropic", "gateway_openai") else f"{pname}_api_key"
    return (f"No API key found for provider {pname}. Set {' or '.join(envs)} env var "
            f"(open a new terminal after install_poste_corp.ps1) or run: /config {cfg_key}=YOUR_KEY")


def calc_cost(model: str, in_tokens: int, out_tokens: int,
              cache_read_tokens: int = 0, cache_creation_tokens: int = 0) -> float:
    from ..agent.providers import calc_cost as _cc
    return _cc(model, in_tokens, out_tokens, cache_read_tokens, cache_creation_tokens)
