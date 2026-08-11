# methodology/cache/

## Purpose
Tests of the A/B cache split of the methodology note —
`context_manager.methodology.split_methodology_for_cache` and
`build_methodology_system_blocks` — and of what `providers.conversion.messages_to_anthropic`
does with the resulting delta. A = the snapshot cached last turn, B = what was appended
since. Mostly deterministic payload construction with no network; two files go further
(a mocked HTTP endpoint, and a live gateway gated on credentials).

## Usage
- `test_cache_wire_e2e.py` — via `bouzecode(mock_api=...)`: the request bodies actually sent carry `cache_control` breakpoints and re-send the methodology context every turn.
- `test_meth_delta_cache_invalidation.py` — byte-level comparison of three successive reconstructed payloads: stable prefix, evolving methodology block, anchor stability, and where the JSON prefix diverges.
- `test_methodology_cache_budget.py` — counts `cache_control` blocks across system and messages for every methodology scenario, against the per-request cap.
- `test_methodology_cache_e2e.py` — live-API diagnostic (`require_api_key`, `capture` fixture from `tests.methodology_cache_e2e_helpers`): turn 2 must read back the methodology cache, including across five growing turns.
- `test_methodology_cache_multiturn.py` — simulated multi-turn dispatch: the snapshot advances, the old block stays byte-stable when idle, every append flavour yields one clean delta fused onto the previous-loop anchor.
- `test_methodology_cache_split.py` — pure split and block-building: first turn, unchanged, appended, replaced (falls back to all-fresh), empty.
