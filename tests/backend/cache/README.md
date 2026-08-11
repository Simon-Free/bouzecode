# cache/

## Purpose
Tests of prompt-cache stability and of the token accounting built on it: what
`agent.minimal_payload.build_messages_for_api` and
`providers.conversion.messages_to_anthropic` put on the wire, where the `cache_control`
breakpoints land, and how `providers.registry.calc_cost` and the loop's `TurnDone`
totals split cache reads from cache writes. Most files rebuild the exact payload the
dispatcher would build and compare it byte for byte; one runs a real two-turn
conversation against the gateway, gated on credentials.

## Usage
- `test_cache_frozen_prefix.py` — the audit note and the injected notes must not mutate the last user message between calls inside one turn.
- `test_cache_multiturn_prefix.py` — a simulated user / assistant / tool-result conversation: payloads share a byte-stable prefix within a turn and stay stable across turns, including with a growing note.
- `test_cache_real_conversation.py` — live gateway (`require_api_key`): `usage.input_tokens` contains both cache reads and cache writes, turn 2 hits the cache, and `calc_cost` uses those semantics.
- `test_cache_tool_loop_diagnosis.py` — system blocks stay byte-stable across tool iterations because `context_manager.audit` output is not in them, and `_find_current_loop_start` pins the breakpoint on the previous user loop rather than a sliding window.
- `test_token_accounting.py` — drives the loop with a fake stream controller: per-turn and cumulative totals, wasted versus read-back cache writes, timing entries carrying the breakdown, session summary arithmetic.
