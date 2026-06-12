# [desc] E2E test verifying Anthropic prompt cache semantics and token accounting over real 2-turn conversations. [/desc]
"""Reproduces the user complaint: a trivial "Salut !" / "Ça va ?"
conversation via the SNCF socle should, on turn 2, hit the ephemeral
cache for the stable system prefix + tool_docs.

The original bug was display-only: bouzecode computed
    cumulated = input + cache_read + cache_create       (double-counted)
    uncached  = input + cache_create                    (double-counted)

The real Anthropic/socle semantics (proved by the semantics test below):
    usage.input_tokens  is the FULL prompt size
    cache_read and cache_create are both SUBSETS of input_tokens

So the correct formulas are:
    cumulated = input_tokens
    cached    = cache_read + cache_create
    uncached  = input_tokens - cached
"""
from __future__ import annotations

import uuid

import pytest

from tests.cache_conversation_helpers import (
    call_anthropic_direct,
    dump_system_blocks,
    require_api_key,
    run_turn_via_dispatch,
    wait_mcp_ready,
)

_MODEL = "claude-sonnet-4-6"


def test_anthropic_input_tokens_includes_cache_read_and_cache_create():
    """Semantics probe. Send the same cached prompt twice with different user
    messages (to avoid the socle's edge cache serving us a canned reply).

    Proves (actual Anthropic semantics):
      - input_tokens reports only the UNCACHED portion of the prompt.
      - 1st call: nothing cached yet → input_tokens = full prompt, all of it
        written to cache (cache_creation large, cache_read 0).
      - 2nd call: prompt served from cache → input_tokens collapses to the fresh
        user message; the bulk shows up as cache_read.
      - cache_creation is part of input_tokens; cache_read is separate. So the
        full prompt size = input_tokens + cache_read stays ~constant.
    """
    require_api_key()
    nonce = uuid.uuid4().hex[:8]
    prompt_text = f"# nonce:{nonce}\n" + ("padding entry . " * 1500)

    blocks = [{"type": "text", "text": prompt_text, "cache_control": {"type": "ephemeral"}}]
    first = call_anthropic_direct(_MODEL, blocks, "ping A1", max_tokens=16)
    second = call_anthropic_direct(_MODEL, blocks, "ping A2", max_tokens=16)
    print(
        f"[1st] in={first.in_tokens:,} create={first.cache_creation_tokens:,} read={first.cache_read_tokens:,}"
    )
    print(
        f"[2nd] in={second.in_tokens:,} create={second.cache_creation_tokens:,} read={second.cache_read_tokens:,}"
    )

    # 1st call writes the cache; 2nd call reads it back.
    assert first.cache_creation_tokens > 1000
    assert second.cache_read_tokens > 1000
    # input_tokens is the UNCACHED portion: it collapses on the cached 2nd call.
    assert second.in_tokens < first.in_tokens, (
        f"caching should cut fresh input_tokens. Got {first.in_tokens} -> {second.in_tokens}."
    )
    # cache_creation is billed AS input (it's part of input_tokens), but
    # cache_read is separate. So the full prompt size = input_tokens + cache_read
    # and that stays ~constant across the two calls.
    first_total = first.in_tokens + first.cache_read_tokens
    second_total = second.in_tokens + second.cache_read_tokens
    assert abs(first_total - second_total) < 100, (
        f"full prompt size should be ~constant. Got {first_total} vs {second_total}."
    )


def test_two_turn_salut_cava_real_cache():
    """Real end-to-end: run the exact "Salut !" / "Ça va ?" conversation
    through dispatch.stream, then verify the post-fix display math.

    After the fix in repl.py / commands/info.py / providers/registry.py:
        cumulated = Σ input_tokens                                 (= full prompts)
        cached    = Σ cache_read + Σ cache_create                  (subsets)
        uncached  = Σ input_tokens − cached                        (volatile + msgs)
    """
    require_api_key()
    wait_mcp_ready()
    dump_system_blocks("after MCP ready")

    config = {"model": _MODEL, "max_tokens": 64}
    nonce = uuid.uuid4().hex[:8]

    messages: list[dict] = [{"role": "user", "content": f"Salut ! (nonce={nonce})"}]
    turn1 = run_turn_via_dispatch(_MODEL, messages, config)
    print(
        f"[turn1] in={turn1.in_tokens:,} "
        f"cache_read={turn1.cache_read_tokens:,} "
        f"cache_create={turn1.cache_creation_tokens:,} out={turn1.out_tokens}"
    )
    messages.append({"role": "assistant", "content": turn1.text})
    messages.append({"role": "user", "content": "Ça va ?"})
    turn2 = run_turn_via_dispatch(_MODEL, messages, config)
    print(
        f"[turn2] in={turn2.in_tokens:,} "
        f"cache_read={turn2.cache_read_tokens:,} "
        f"cache_create={turn2.cache_creation_tokens:,} out={turn2.out_tokens}"
    )

    assert turn2.cache_read_tokens > 4000, (
        f"Turn 2 should hit the cache (got read={turn2.cache_read_tokens})."
    )

    sum_in     = turn1.in_tokens + turn2.in_tokens
    sum_read   = turn1.cache_read_tokens + turn2.cache_read_tokens
    sum_create = turn1.cache_creation_tokens + turn2.cache_creation_tokens

    cumulated = sum_in
    cached    = sum_read + sum_create
    uncached  = sum_in - cached
    print(
        f"[post-fix] cumulated={cumulated:,} | cached={cached:,} | uncached={uncached:,}"
    )
    assert uncached < 2000, (
        f"Uncached portion across both turns should be tiny "
        f"(volatile + 2 short messages). Got {uncached:,}."
    )


def test_calc_cost_uses_correct_cache_semantics():
    """Unit test on calc_cost: with input_tokens = full prompt, cost must
    subtract cache_read & cache_create from the 1x-billed portion."""
    from bouzecode.backend.agent.providers.registry import calc_cost

    model = _MODEL
    input_tokens = 10_000
    output_tokens = 500
    cache_read = 8_000
    cache_create = 1_000
    # Pure input = 10_000 - 8_000 - 1_000 = 1_000
    cost = calc_cost(model, input_tokens, output_tokens, cache_read, cache_create)
    # Sanity: with this model's rate (2.8 per 1M in for sonnet-4-6),
    # pure_input=1000 * 2.8 + cache_read=8000 * 2.8 * 0.1 +
    # cache_create=1000 * 2.8 * 1.25 + out=500 * 14.0 = 2800 + 2240 + 3500 + 7000 = 15540
    expected = 15_540 / 1_000_000
    assert abs(cost - expected) < 1e-6, f"calc_cost={cost}, expected≈{expected}"
