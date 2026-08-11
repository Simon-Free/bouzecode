# agent/providers/

## Purpose
Maps a user-facing model name to a provider (Anthropic, OpenRouter, or an
OpenAI-compatible gateway declared in the environment), resolves its API key and
price, and defines the neutral event types every backend streams back.

## Usage
- `registry.py` — `PROVIDERS`, `MODELS`, `COSTS`, `resolve_provider()`, `detect_provider()`, `bare_model()`, `model_uses_native_tools()`, `anthropic_endpoint_serves_native_tools()`, `gateway_base_url()`, `gateway_models()`, `get_api_key()`, `get_openrouter_key()`, `get_gateway_key()`, `get_provider_key()`, `calc_cost()` — the routing table (model list, context limit, key env var, base URL per provider), the retry constants shared by the backends, and per-token cost with cache-read/cache-write rates.
- `types.py` — `StreamStarted`, `TextChunk`, `ThinkingChunk`, `ToolCallParsed`, `ToolIdRemap`, `SystemPayload`, `AssistantTurn`, `sanitize_tool_name()`, `_supports_adaptive_thinking()` — the objects a backend yields, in order: the system payload, then chunks, then one final turn carrying text, tool calls and token counts.
- `conversion.py` — `sanitize_messages()`, `messages_to_anthropic()` — neutral messages to the Anthropic wire using the XML tool protocol; fills in tool results that an interrupted turn never produced, folds image results into content blocks, and places the `cache_control` breakpoint on the last message of the previous user loop.
- `missing_key.py` — `MissingApiKeyError`, `KEY_HINTS`, `configured_providers()`, `example_models()`, `missing_key_message()`, `startup_key_warning()` — the diagnosis shown when the chosen model's provider has no key: which providers do hold one and which `--model` they serve.
- `__init__.py` re-exports the public surface (types, registry, conversion, `stream_anthropic`, `stream`).

## Subfolders
| Folder | Description |
|--------|-------------|
| `backends/` | Per-provider streaming and the dispatcher that selects one |
