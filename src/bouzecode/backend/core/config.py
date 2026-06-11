# [desc] Configuration loading, saving, and defaults for multi-provider Bouzecode CLI tool. [/desc]
"""Configuration management for Bouzecode (multi-provider)."""
import os
import json
from pathlib import Path

CONFIG_DIR        = Path.home() / ".bouzecode"
CONFIG_FILE       = CONFIG_DIR  / "config.json"
HISTORY_FILE      = CONFIG_DIR  / "input_history.txt"
SESSIONS_DIR      = CONFIG_DIR  / "sessions"
DAILY_DIR         = SESSIONS_DIR / "daily"       # daily/YYYY-MM-DD/session_*.json
SESSION_HIST_FILE = SESSIONS_DIR / "history.json" # master: all sessions ever

# kept for backward-compat (/resume still reads from here)
MR_SESSION_DIR = SESSIONS_DIR / "mr_sessions"

DEFAULTS = {
    "model":            "claude-opus-4-6",
    "max_tokens":       64000,
    "permission_mode":  "auto",   # auto | accept-all | manual
    "verbose":          False,
    "thinking":         True,
    "thinking_mode":    "extended",  # "extended" (API thinking) | "loud" (visible <thinking> tags)
    "thinking_effort":  "high",   # adaptive thinking: low | medium | high | max
    "thinking_budget":  32000,    # fallback for non-adaptive models (type=enabled)
    "custom_base_url":  "",       # for "custom" provider
    "max_tool_output":  32000,
    "thinking_overflow_limit": 20000,  # chars of thinking before forced action

    "max_agent_depth":  3,
    "max_concurrent_agents": 3,
    "database_kind":         "rec",  # cassiodb environment (dev/rec/pp/prod/local)
    "gitlab_url":            "https://gitlab-repo-mob.apps.eul.sncf.fr",
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
    return detect_provider(cfg.get("model", "claude-opus-4-6"))


def has_api_key(cfg: dict) -> bool:
    """Check whether the active provider has an API key configured."""
    from ..agent.providers.registry import get_provider_key
    pname = current_provider(cfg)
    key = get_provider_key(pname, cfg)
    return bool(key)


def calc_cost(model: str, in_tokens: int, out_tokens: int,
              cache_read_tokens: int = 0, cache_creation_tokens: int = 0) -> float:
    from ..agent.providers import calc_cost as _cc
    return _cc(model, in_tokens, out_tokens, cache_read_tokens, cache_creation_tokens)
