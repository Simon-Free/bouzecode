# providers/wire/

## Purpose
Covers what the agent actually puts on the wire: the message conversion functions
(`providers.conversion`, `backends.anthropic_native`, `sanitize_tool_name`) and the
payload builder `bouzecode.backend.agent.minimal_payload`. Conversion is tested as
pure functions on hand-built message lists; payload minimality is checked through a
real `bouzecode()` conversation driven by `MockLLM`, inspecting the recorded calls.

## Usage
- `test_conversion_missing_inputs.py` — `messages_to_anthropic` tolerates a tool call whose arguments key is missing, plural or singular.
- `test_fake_llm.py` — the `MockLLM` test double itself: text, tool calls, call count, exhaustion, recorded messages.
- `test_minimal_payload.py` — `build_messages_for_api`, `build_minimal_payload`, `_strip_thinking_blocks`, `_strip_thinking_from_messages`.
- `test_minimal_wire.py` — after a turn of long prose plus housekeeping tool calls, the next request carries only the tool results.
- `test_native_tool_result_roundtrip.py` — `messages_to_anthropic_native`: batches paired with their results, an orphaned result re-declared, image results kept inside their block, no empty result sent.
- `test_tool_name_sanitization.py` — `sanitize_tool_name` on valid, corrupted, empty and unicode names, and how an invalid name is reported back to the model.
