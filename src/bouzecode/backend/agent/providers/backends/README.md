# providers/backends/

## Purpose
One module per wire protocol — Anthropic (native `tool_use` blocks or XML tool
calls in the text) and OpenAI-compatible endpoints (OpenRouter, or a gateway) —
plus the dispatcher that builds the system blocks and picks the right streamer.

## Usage
- `dispatch.py` — `stream()` — the single entry point: resolves provider and key, builds the system blocks (stable prompt, profile extra, tool docs, methodology and its delta, seed placeholder, volatile tail), injects the audit note, working-memory notes and the per-turn reminder into a wire-only copy of the messages, yields a `SystemPayload` carrying that exact wire, then delegates. Helpers `_inject_into_last_user_message()`, `_append_to_last_user_message()`, `_resolve_cache_control()`, `_require_key()`.
- `anthropic_stream.py` — `stream_anthropic()` — the Anthropic SSE loop: token usage from `message_start`/`message_delta`, text and thinking chunks, tool calls read from native blocks or parsed from XML, mid-stream drop retried with backoff, truncated blocks finalized.
- `anthropic_native.py` — `tool_schemas_to_anthropic()`, `messages_to_anthropic_native()`, `NativeToolUseAccumulator` — schemas for the API `tools` param (scheduling params added), typed `tool_use`/`tool_result` wire messages with the cache breakpoint, and per-index accumulation of interleaved `input_json_delta` events.
- `anthropic_helpers.py` — `_create_anthropic_stream_with_retry()`, `_iter_stream_resilient()`, `_StreamInterrupted`, `_install_sse_diagnostic_patch()`, `_guess_tool_name()`, `_TRANSIENT_GATEWAY_MARKERS` — retry policy per error class (rate limit budget, connection/server backoff, transient gateway 400, warm-up 401), inter-chunk stall detection, and tool-name recovery from argument keys.
- `anthropic_client.py` — `build_anthropic_client()` — SDK client over an httpx transport with TCP keep-alive so a dropped idle connection surfaces as an error instead of a stall.
- `openrouter_stream.py` — `stream_openrouter()` — the OpenAI-compatible SSE loop, reusable for any gateway through `base_url`, `session_factory`, `send_reasoning`, `reasoning_effort` and `provider_label`; retries a degenerate empty completion.
- `openrouter_native.py` — `tool_schemas_to_openai()`, `messages_to_openai_native()`, `accumulate_tool_call_deltas()`, `finalize_tool_calls()`, `_SCHEDULING_PROPS` — OpenAI function-calling conversion, including synthesizing the assistant `tool_calls` that a minimized payload dropped so every result pairs with a call.
- `openrouter_transport.py` — `build_session()`, `build_plain_session()`, `iter_sse()` — a requests session with or without the outbound proxy, and SSE line parsing with an optional raw dump.
- `openrouter_retry.py` — `post_with_retry()`, `BACKOFFS_S` — backoff on 429/5xx, one retry on 400 to land on another upstream provider.
- `test_anthropic_helpers_gateway_retry.py` — checks that a 400 carrying a transient-gateway marker is retried and a genuine client 400 propagates at once.

## Subfolders
| Folder | Description |
|--------|-------------|
| `tests/` | Wire-mutation contract of `dispatch.stream()` |
