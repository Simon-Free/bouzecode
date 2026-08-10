# providers/

## Purpose
Multi-provider LLM streaming (Anthropic, OpenAI-compat, Ollama). Handles API-key detection, model-name parsing, message conversion, and stream normalization.

## Usage
- `registry.py` — `PROVIDERS`, `COSTS`, `detect_provider()`, `bare_model()`, `get_api_key()`, `calc_cost()`
- `types.py` — `StreamStarted`, `TextChunk`, `ThinkingChunk`, `AssistantTurn`, `sanitize_tool_name()`
- `conversion.py` — `tools_to_openai()`, `sanitize_messages()`, `messages_to_anthropic()`, `messages_to_openai()`
- `backends/` — provider-specific streaming
- `__init__.py` re-exports everything for `from providers import X`

## Subfolders
| Folder | Description |
|--------|-------------|
| `backends/` | Per-provider streaming: Anthropic, OpenAI-compat, Ollama, dispatch |
