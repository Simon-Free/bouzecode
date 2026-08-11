# backends/tests/

## Purpose
Covers the two wire guarantees of `dispatch.stream()`: the per-turn reminders
reach the last user-facing message whatever its role, and the payload persisted
for the context viewer is the wire actually sent. Approach: direct calls on the
dispatch helpers, plus one turn driven through `loop_turn.stream_llm_turn` with a
fake streamer and `monkeypatch` — no network, no model.

## Usage
- `test_fresh_reminder_injection.py` — the reminder and the audit note land in a wire whose last message is a `tool` result (string or block list), and a real user message stays the preferred target.
- `test_wire_dump_exactness.py` — the record written to `turns.jsonl` contains the mutated wire carried by `SystemPayload`, not the pre-dispatch payload.
