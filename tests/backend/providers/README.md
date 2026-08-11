# providers/

## Purpose
Tests of the LLM provider layer, `bouzecode.backend.agent.providers`: the model
registry and cost table, the Anthropic and OpenRouter streaming backends, retry
and stream-resilience policies, and the missing-key diagnosis. Almost everything
here runs offline — fake `requests` sessions, fake Anthropic clients and scripted
SSE installed with `monkeypatch` — except the `mock_api` files, which drive the
whole real pipeline through the `bouzecode()` harness against a fake Anthropic
HTTP/SSE server.

## Usage
- `anthropic_sse_replay.py` — `sse`, `opening`, `text`, `tool_open`, `args`, `close`, `closing`, `replay_stream`, `tool_calls_of`, `turn_of` — scripts an SSE event sequence and replays it through the real `stream_anthropic`.
- `test_anthropic_native_e2e.py` — native `tool_use` blocks: single, parallel, truncated; schemas reaching the `tools` param; XML path untouched when native is off.
- `test_cache_ttl_flag.py` — `_resolve_cache_control` in `backends.dispatch`: when a 1h cache TTL is attached.
- `test_deepseek_http_payload.py` — captures the actual HTTP body sent to OpenRouter and asserts `tools`, `tool_choice` and system content.
- `test_deepseek_payload_tools.py` — the `SystemPayload` built for an OpenRouter model carries the Methodology/Snippet schemas and drops the XML tool docs in native mode.
- `test_empty_completion_retry.py` — an empty completion is retried within budget; substantive and reasoning-only answers are not.
- `test_inter_chunk_timeout.py` — `_iter_stream_resilient` stall detection: a stalled or erroring stream raises `_StreamInterrupted`, an empty one completes.
- `test_meth_prompt_variant.py` — placement of the methodology rule at the end of the native system text, and the switch that removes it.
- `test_missing_api_key_message.py` — `providers.missing_key`: `configured_providers`, `missing_key_message`, `startup_key_warning`, `MissingApiKeyError` raised on a turn.
- `test_mock_api_e2e.py` — full pipeline against the fake server: wire payload recorded, a tool_use split across chunks reassembled, server error retried, thinking in the transcript.
- `test_no_claude_md_in_prompt.py` — `build_system_prompt_parts` keeps CLAUDE.md content out of the stable prompt.
- `test_openrouter_conversion.py` — `_system_text`, `_content_to_text`, `_messages_to_openai` in `backends.openrouter_stream`.
- `test_openrouter_registry.py` — `resolve_provider` and `calc_cost` per model slug, including cache-read overrides.
- `test_openrouter_retry.py` — backoff policy: 429 and 5xx retried, 400 retried once, other 4xx raised immediately.
- `test_platform_hints_in_bash_tool.py` — platform hints belong to the Bash tool description, not the system prompt.
- `test_resilience_mock_api_e2e.py` — rate limit, repeated server errors, malformed SSE and a cut connection, each played as a conversation.
- `test_retry.py` — `_create_anthropic_stream_with_retry` against an instrumented clock: budget exhaustion, eventual success, non-retryable errors.
- `test_stream_resilience.py` — the resilient SSE iterator on decode errors, `httpx` read errors, clean streams, and `_install_sse_diagnostic_patch`.

## Subfolders
| Folder | Description |
|--------|-------------|
| `auth/` | Authentication and model-access failures. |
| `dispatch/` | Provider routing and system-payload assembly in `backends.dispatch`. |
| `wire/` | What the message payload looks like on the wire. |
