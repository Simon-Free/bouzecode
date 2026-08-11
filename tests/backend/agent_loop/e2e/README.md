# agent_loop/e2e/

## Purpose
Full conversations run through the `bouzecode()` harness (`tests/e2e_harness`),
split by LLM source: a real API, a scripted `MockLLM`, and a suite checking the
token-saving behaviour of tools and system prompt.

## Usage
- `test_e2e_hello.py` — single-turn and multi-turn conversations against a real LLM; `require_api_key` from `tests/cache_conversation_helpers` self-skips without credentials.
- `test_e2e_mock.py` — the harness driven by `MockLLM` raw-XML replies: simple reply, multi-turn, tool-call cycle, `tools` passed as a dict or as a callable, state preservation, recorded messages, malformed XML yielding no tool.
- `test_e2e_token_optimizations.py` — Edit/Write results in `state.messages`, `GetFolderDescription` default depth, Bash output truncation, and the code-discovery prompt reaching the system prompt built by `core.context.build_system_prompt_parts` from `backend.profiles`.
