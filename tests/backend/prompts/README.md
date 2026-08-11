# prompts/

## Purpose
Covers system-prompt assembly in `bouzecode.backend.core.context`
(`build_system_prompt`, `build_system_prompt_parts`, `get_memory_context`), the
prompt assets loaded from `core._embedded_data`, and the conformity rule that a
prompt surface may only name tools the agent can actually call. Mostly direct calls
to the real builder with a config dict, reading the produced text; one file runs a
`bouzecode()` conversation with `MockLLM` to prove the built prompt reaches the model.

## Usage
- `test_code_discovery_prompt.py` — the discovery guidance ships in the default profile layer, loaded through `load_profiles_from_dir`.
- `test_get_memory_context.py` — `build_system_prompt_parts` returns two strings and `get_memory_context` exists and returns text.
- `test_manager_prompt.py` — the manager's lean prompt: which bookkeeping sections drop, and that its role stays typology and sequencing.
- `test_prompt_build_e2e.py` — the real prompt builds and lands on the wire in a conversation.
- `test_prompt_registry_conformity.py` — `prompt_surfaces`/`violations` per profile: no prompt or guard message names a tool outside `enabled_tools_for_profile`, plus self-tests that the check catches a reintroduced violation.
- `test_system_prompt_format.py` — the template renders without `KeyError` and leaves no unsubstituted placeholder.
- `test_system_prompts_loading.py` — every `.txt` prompt asset is exported, reaches the built prompt, and the plan-mode and platform-hint variants render.
