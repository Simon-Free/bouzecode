# agent/providers/backends/

## Purpose
Unit tests of `agent.providers.backends.dispatch`, covering the reminder text
appended to the outgoing message list just before the request leaves.

## Usage
- `test_fresh_reminder.py` — `_append_to_last_user_message` (string content, content given as a block list, no user message, targeting the last user message rather than the first), the wire-only guarantee that the caller's list and its dicts stay untouched, and the `_FRESH_REMINDER` text gated by the `BOUZECODE_FRESH_REMINDER` environment variable (`"0"` disables it, anything else keeps it on).
