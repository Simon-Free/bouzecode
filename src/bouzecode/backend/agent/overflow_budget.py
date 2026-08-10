"""Dynamic thinking-overflow budget, scaled to the cost of the context.

The cut+retry caused by an overflow costs roughly the price of re-reading the
context: cache-read tokens (X) plus the fresh input (Y). Expressed in output
tokens via the price ratios (cache-read 0.1x input, output 5x input), the
break-even is:

    O* = X / cache_divisor + Y / fresh_divisor      (= X/50 + Y/5)

So a pricier context to re-process earns proportionally more thinking before we
pay that retry tax. The result is floored at the configured minimum (the legacy
fixed limit) and capped at the configured max, then converted chars<->tokens.

X and Y are read from the most recent completed LLM turn (state.timing_entries);
on the first turn there is no accounting yet, so we fall back to the floor.
"""

from __future__ import annotations


def _last_llm_context_tokens(state) -> tuple[int, int]:
    """Return (context_tokens, fresh_tokens) of the most recent LLM turn.

    context_tokens (X) = everything re-read on a retry (cache + fresh input).
    fresh_tokens (Y)   = that turn's uncached input (a churn proxy).
    Returns (0, 0) when no LLM turn has completed yet.
    """
    for entry in reversed(state.timing_entries):
        if entry.get("phase") == "llm":
            fresh = entry.get("in_tokens", 0)
            cached = entry.get("cache_read_tokens", 0) + entry.get("cache_creation_tokens", 0)
            return fresh + cached, fresh
    return 0, 0


def dynamic_overflow_limit(state, config: dict) -> int:
    """Chars of thinking allowed before forcing action, scaled to context cost.

    Returns 0 when overflow is disabled (floor set to 0).
    """
    floor_chars = config.get("thinking_overflow_limit", 20000)
    if not floor_chars:
        return 0

    context_tokens, fresh_tokens = _last_llm_context_tokens(state)
    if context_tokens == 0:
        return floor_chars

    cache_divisor = config.get("thinking_cache_divisor", 50)
    fresh_divisor = config.get("thinking_fresh_divisor", 5)
    chars_per_token = config.get("thinking_chars_per_token", 4)
    max_chars = config.get("thinking_overflow_max", 80000)

    thinking_tokens = context_tokens / cache_divisor + fresh_tokens / fresh_divisor
    dynamic_chars = int(thinking_tokens * chars_per_token)
    return max(floor_chars, min(dynamic_chars, max_chars))
