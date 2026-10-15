# [desc] Models that refuse a forced tool_choice, and the tool_choice actually sent to them. [/desc]
"""Forced tool_choice, degraded to "auto" for the models that refuse it.

Enforcement recovery calls (enforcement_call._ask_forced) force the choice:
{"type": "function", "function": {"name": <tool>}} or "required". Some models
answer HTTP 400 to any forced choice and accept only "auto" (or "none"):

  - Z.AI (GLM): "Tool choice must be auto".
  - Claude Opus 5.5, Sonnet 5.5, Fable 5.1, Mythos 5.1: forced `any`/`tool` is
    rejected (measured 2026-10-05, session 0a3ed5c5, claude-opus-5-5 via the
    preprod gateway: `litellm.BadRequestError: BedrockException ...`).

The recovery system prompt already names the one tool to call, so "auto" keeps
the call working; if the model still answers without it, the recovery returns
nothing and the loop goes on ("recovery failed — continuing")."""
from __future__ import annotations

import re

# Bare ids (no vendor/region prefix, no version/date suffix) of the Claude models
# that refuse a forced tool_choice.
_CLAUDE_AUTO_ONLY = ("claude-opus-5-5", "claude-sonnet-5-5",
                     "claude-fable-5-1", "claude-mythos-5-1")


def _bare_id(model: str) -> str:
    """'anthropic/claude-opus-5-5', 'eu.anthropic.claude-opus-5-5-v1:0' -> 'claude-...'."""
    bare = model.lower().rsplit("/", 1)[-1]
    bare = bare.rsplit("anthropic.", 1)[-1]
    # OpenRouter writes the version with a dot: 'claude-opus-5.5' -> 'claude-opus-5-5'.
    return re.sub(r"^(claude-[a-z]+-\d+)\.(\d+)", r"\1-\2", bare)


def _is_zai_model(model: str) -> bool:
    """Z.AI (GLM) models, as an alias ("glm-5.2") or a resolved id ("z-ai/glm-5.2")."""
    return _bare_id(model).startswith("glm-") or model.lower().startswith("z-ai/")


def _is_claude_auto_only(model: str) -> bool:
    bare = _bare_id(model)
    return any(bare == name or bare.startswith((name + "-", name + "@", name + ":", name + "["))
               for name in _CLAUDE_AUTO_ONLY)


def refuses_forced_tool_choice(model: str) -> bool:
    """True when `model` answers HTTP 400 to a forced tool_choice (only auto/none pass)."""
    return _is_zai_model(model) or _is_claude_auto_only(model)


def resolve_tool_choice(model: str, config: dict):
    """OpenAI-style tool_choice to send: the forced choice of a recovery call, else "auto"
    (also "auto" when the model refuses a forced choice)."""
    choice = config.get("_tool_choice") or "auto"
    if choice != "auto" and refuses_forced_tool_choice(model):
        return "auto"
    return choice
