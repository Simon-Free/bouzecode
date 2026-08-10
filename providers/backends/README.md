# providers/backends/

## Purpose
Per-provider streaming implementations and the dispatcher that routes a `stream()` call to the right backend.

## Usage
- `anthropic_stream.py` — `stream_anthropic()` with SSE resilience
- `anthropic_helpers.py` — retry wrappers, SSE diagnostic patch, tool-name recovery
- `openai_compat.py` — `stream_openai_compat()` for OpenAI-shaped APIs (Kimi, DeepSeek, Groq, etc.)
- `ollama.py` — `stream_ollama()`, `list_ollama_models()`
- `dispatch.py` — `stream(model, messages, tools, config)` → chooses backend
