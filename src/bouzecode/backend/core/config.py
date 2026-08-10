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
    "model":            "claude-opus-4-8",
    "max_tokens":       64000,
    # Auto task-routing classifier (feature/bug profile). OFF by default: it fires
    # a tiny max_tokens=12 side-call at session start whose truncation prints an
    # alarming (and here irrelevant) banner. Set True to re-enable. --profile still
    # routes explicitly regardless of this flag.
    "task_classification": False,
    "permission_mode":  "auto",   # auto | accept-all | manual
    "verbose":          False,
    "thinking":         True,
    "thinking_mode":    "extended",  # "extended" (API thinking) | "loud" (visible <thinking> tags)
    "native_reasoning": False,    # opt-in: use the API's native reasoning channel (ThinkingChunk). OFF by default — the model reasons via manual <thinking> text routed into thinking_parts by loop_turn.
    "thinking_effort":  "high",   # adaptive thinking: low | medium | high | max
    "thinking_budget":  32000,    # fallback for non-adaptive models (type=enabled)
    "custom_base_url":  "",       # for "custom" provider
    "max_tool_output":  32000,
    # Overflow budget is dynamic: limit_chars = max(floor, X/cache_div + Y/fresh_div)
    # in tokens, then *chars_per_token, capped at the max. X = context re-read on a
    # retry (cache + fresh input of the last turn), Y = that turn's fresh input. The
    # divisors come from the price ratios (cache-read 0.1x in, output 5x in => X/50,
    # Y/5): a pricier context to re-process earns proportionally more thinking before
    # we pay the cut+retry tax. See thinking_summary.py / loop_turn.py.
    "thinking_overflow_limit": 20000,  # chars — MINIMUM (floor); 0 disables overflow
    "thinking_overflow_max":   80000,  # chars — ceiling (anti-runaway)
    "thinking_cache_divisor":  50,     # cached tokens (X) -> thinking tokens allowed
    "thinking_fresh_divisor":  5,      # fresh tokens (Y) -> thinking tokens allowed
    "thinking_chars_per_token": 4,     # tokens -> chars conversion (FR + code mix)
    # Agent-specific tail appended to the thinking-overflow nudge. The default
    # (coding) agent verifies hypotheses via tests; other agents
    # set their own or leave it empty. Only the overflow notice + "act now" and
    # the Methodology/Snippet behavior are common to every agent.
    "overflow_action_hint": (
        "Write a `test_*.py` file to verify the hypotheses you considered above. "
        "Run it. Let the test results guide your next step — not more thinking."
    ),

    "max_agent_depth":  3,
    "max_concurrent_agents": 3,
    # Base URL of the GitLab instance hosting your plugins / agent catalog.
    # Empty by default; set it here or via the BOUZECODE_GITLAB_URL env var.
    "gitlab_url":            os.environ.get("BOUZECODE_GITLAB_URL", ""),
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
    return detect_provider(cfg.get("model", "claude-opus-4-8"))


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
