# providers/dispatch/

## Purpose
Covers `bouzecode.backend.agent.providers.backends.dispatch` — the entry point that
picks a backend for a model, assembles the `SystemPayload`, and decides between the
XML and native tool protocols (with `registry.model_uses_native_tools`). The tests
call `stream()` for a single event and read the payload it built, with provider keys
and environment switches set through `monkeypatch`; nothing leaves the process.

## Usage
- `test_dispatch_inject.py` — `_inject_into_last_user_message` for string content, block-list content, no user message, and multiple user messages.
- `test_dispatch_openrouter_routing.py` — model slug decides the provider: a missing OpenRouter key raises `MissingApiKeyError`, and each path routes without the other provider's key.
- `test_dispatch_system_override.py` — an explicit `system` argument replaces the default prompt and its standard sections; an empty one falls back to the default.
- `test_native_tools_switch.py` — XML by default on the Anthropic path, the environment escape hatch both ways, profile config outranking it, tool schemas versus XML tool docs, and OpenRouter staying native regardless.
