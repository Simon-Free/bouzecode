# [desc] Tests the dynamic thinking-overflow budget scaled to context cost. [/desc]
"""The overflow limit grows with the cost of re-reading the context.

limit = max(floor, X/cache_div + Y/fresh_div) tokens, *chars_per_token, capped.
"""

from types import SimpleNamespace

from bouzecode.backend.agent.overflow_budget import (
    dynamic_overflow_limit,
    _last_llm_context_tokens,
)
from bouzecode.backend.core.config import DEFAULTS


def _state(timing_entries):
    return SimpleNamespace(timing_entries=timing_entries)


def _llm_entry(in_tokens, cache_read, cache_creation=0):
    return {
        "phase": "llm",
        "in_tokens": in_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
    }


def test_floor_when_no_prior_llm_turn():
    """First turn (no accounting yet) falls back to the configured floor."""
    limit = dynamic_overflow_limit(_state([]), DEFAULTS)
    assert limit == DEFAULTS["thinking_overflow_limit"]


def test_zero_floor_disables_overflow():
    config = {**DEFAULTS, "thinking_overflow_limit": 0}
    assert dynamic_overflow_limit(_state([_llm_entry(5000, 100000)]), config) == 0


def test_small_context_stays_at_floor():
    """A tiny context yields a budget below the floor -> floor wins."""
    # X=3000, Y=3000 -> 3000/50 + 3000/5 = 60 + 600 = 660 tokens -> 2640 chars < floor
    state = _state([_llm_entry(in_tokens=3000, cache_read=0)])
    assert dynamic_overflow_limit(state, DEFAULTS) == DEFAULTS["thinking_overflow_limit"]


def test_large_context_scales_above_floor():
    """A big cached context earns more thinking than the floor."""
    # X = 5000 + 400000 = 405000, Y = 5000
    # 405000/50 + 5000/5 = 8100 + 1000 = 9100 tokens -> *4 = 36400 chars
    state = _state([_llm_entry(in_tokens=5000, cache_read=400000)])
    limit = dynamic_overflow_limit(state, DEFAULTS)
    assert limit == 36400
    assert limit > DEFAULTS["thinking_overflow_limit"]


def test_capped_at_max():
    """An enormous context is clamped to the configured ceiling."""
    state = _state([_llm_entry(in_tokens=10000, cache_read=5_000_000)])
    assert dynamic_overflow_limit(state, DEFAULTS) == DEFAULTS["thinking_overflow_max"]


def test_uses_most_recent_llm_turn_ignoring_tool_entries():
    """Tool-phase entries are skipped; the latest llm turn drives the budget."""
    state = _state([
        _llm_entry(in_tokens=5000, cache_read=400000),
        {"phase": "Bash", "duration": 1.0},
        {"phase": "Read", "duration": 0.5},
    ])
    context_tokens, fresh_tokens = _last_llm_context_tokens(state)
    assert context_tokens == 405000
    assert fresh_tokens == 5000
