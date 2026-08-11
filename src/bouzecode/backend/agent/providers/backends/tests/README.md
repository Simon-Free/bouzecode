# backends/tests/

## Purpose
Covers the wire guarantees of `dispatch.stream()` and the retry policy of the Anthropic
helpers: the per-turn reminders reach the last user-facing message whatever its role, the
payload persisted for the context viewer is the wire actually sent, and a transient
gateway 400 is retried while a genuine client 400 is not. Approach: direct calls on the
helpers, plus one turn driven through `loop_turn.stream_llm_turn` with a fake streamer and
`monkeypatch` — no network, no model.

This tree is in `testpaths`. It was not, and `test_wire_dump_exactness.py` had been raising
`KeyError` unseen ever since the payload journal went delta-encoded.

## Usage
- `test_fresh_reminder_injection.py` — the reminder and the audit note land in a wire whose last message is a `tool` result (string or block list), and a real user message stays the preferred target.
- `test_wire_dump_exactness.py` — the payload `turns.jsonl` gives back for a turn, read through `core/payload_view` (which folds the deltas), is exactly the mutated wire carried by `SystemPayload` — not the pre-dispatch payload.
- `test_anthropic_helpers_gateway_retry.py` — a 400 carrying a transient-gateway marker is retried; a genuine client 400 propagates at once.
