# [desc] Builds the actionable "no API key" diagnosis: which providers ARE configured and how to pick a model they serve. [/desc]
"""Turn a missing API key into a message a newcomer can act on.

The chosen model decides the provider; the provider decides which environment
variable must carry a key. When that key is absent the run cannot start — but
the user often HAS a key for another provider, so the only thing missing is a
`--model` that the configured provider serves. This module says exactly that.
"""
from __future__ import annotations

from .registry import (
    ENV_GATEWAY_API_KEY,
    ENV_GATEWAY_BASE_URL,
    ENV_GATEWAY_MODELS,
    GATEWAY_PROVIDER,
    PROVIDERS,
    get_provider_key,
    resolve_provider,
)


class MissingApiKeyError(RuntimeError):
    """No API key for the provider serving the chosen model.

    A configuration error, not a bug: the CLI prints `str(exc)` and exits
    instead of dumping a traceback."""


# How to give each provider a key, in the exact form expected in `.env`.
KEY_HINTS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY=sk-ant-...",
    "openrouter": "OPENROUTER_KEY=sk-or-...",
    GATEWAY_PROVIDER: (
        f"{ENV_GATEWAY_API_KEY}=...  (plus {ENV_GATEWAY_BASE_URL}="
        f"https://gateway.example.com and {ENV_GATEWAY_MODELS}=your-model)"
    ),
}


def configured_providers(config: dict) -> list[str]:
    """Provider names that currently hold a usable API key."""
    return [name for name in PROVIDERS if get_provider_key(name, config)]


def example_models(provider_name: str) -> list[str]:
    """A couple of model names the provider serves, for a copy-pastable hint."""
    return list(PROVIDERS.get(provider_name, {}).get("models", []))[:3]


def _switch_lines(providers: list[str]) -> list[str]:
    lines = []
    for name in providers:
        models = example_models(name)
        if not models:
            # The gateway declares its models in the environment; without
            # BOUZECODE_GATEWAY_MODELS there is nothing to suggest.
            lines.append(f"    {name}: no model declared "
                         f"(set {ENV_GATEWAY_MODELS})")
            continue
        lines.append(f"    {name}: --model {models[0]}"
                     + (f"   (also: {', '.join(models[1:])})" if models[1:] else ""))
    return lines


def missing_key_message(provider_name: str, model: str, config: dict) -> str:
    """The full, actionable diagnosis shown when a run cannot start."""
    others = [p for p in configured_providers(config) if p != provider_name]
    lines = [
        "",
        f"  No API key for provider '{provider_name}', which serves model '{model}'.",
        "",
    ]
    if others:
        lines.append(f"  Providers already configured here: {', '.join(others)}.")
        lines.append("  Either pick a model one of them serves:")
        lines.extend(_switch_lines(others))
        lines.append("  (or `/model <name>` inside the REPL, which remembers the choice)")
        lines.append("")
        lines.append(f"  ...or give '{provider_name}' its key:")
        lines.append(f"    {KEY_HINTS.get(provider_name, provider_name.upper() + '_API_KEY=...')}")
    else:
        lines.append("  No provider is configured at all. Put one of these in a `.env`")
        lines.append("  file at the repo root (or export it), then relaunch:")
        for name in PROVIDERS:
            lines.append(f"    {KEY_HINTS.get(name, name.upper() + '_API_KEY=...')}")
    lines.append("")
    return "\n".join(lines)


def startup_key_warning(model: str, config: dict) -> str | None:
    """One-line launch warning, or None when the chosen model can actually run.

    The old banner said "ANTHROPIC_API_KEY not set" even when OpenRouter was
    configured and working; it now names the model that cannot run and the keys
    that are present."""
    provider_name = resolve_provider(model)[0]
    if get_provider_key(provider_name, config):
        return None
    others = [p for p in configured_providers(config) if p != provider_name]
    if others:
        suggestions = ", ".join(
            f"--model {m}" for m in (example_models(others[0])[:1] or [])
        )
        return (
            f"No API key for '{provider_name}' (model {model}). "
            f"Configured: {', '.join(others)}"
            + (f" — try {suggestions}." if suggestions else ".")
        )
    return (
        f"No API key for '{provider_name}' (model {model}), and no other provider "
        f"is configured. Set {KEY_HINTS.get(provider_name, 'a provider key')}"
    )
