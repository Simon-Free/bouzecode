# agents_map/

## Purpose
Tests of `bouzecode.backend.tools.agents_map` — the generated folder maps: `manifest`
(hashes and the `SYMBOLS.md` name), `regen` (LLM regeneration), `serve` (cache, lock,
edit hook), `contract` and `nesting` (what a map is allowed to claim), and `progress`.
The model is a local fake counting its calls; the contract file re-checks every map
already committed under `src/` against the live AST; two files drive real `bouzecode()`
conversations.

## Usage
- `conftest.py` — `pkg` (a two-file package in `tmp_path`), `fake_llm` (call-counting `FakeLLM`), `fresh_map` (writes a coherent map plus lock), `good_map`, `bad_nesting_map`.
- `test_map_contract.py` — every committed map that claims to be current really is, none mentions a subfolder, every call line names the file it lives in, a control-flow label is not a call, the navigation protocol is in the prompt, and the feature has exactly one global off switch.
- `test_map_guards.py` — never write a false map (a non-conforming output leaves the old one), an invented call edge is named back to the model, a folder the agent just edited is not regenerated on its own churn, a held lock and a provider outage both serve the stale map, a code-free folder gets none, and a truncated or incomplete root map is refused.
- `test_progress.py` — a streaming client makes `regen.generate_symbols` report the growing line count through `progress.progress_reporter`; a blocking client falls back silently; the reporter is throttled.
- `test_push_and_pull_e2e.py` — writing code in a conversation records the folder as self-authored; a non-code file never claims one.
- `test_read_fallbacks_e2e.py` — a `Read` with a wrong symbol returns the file, a wrong path resolves by basename, an ambiguous basename lists the candidates.
- `test_symbol_map.py` — the model can call `SymbolMap` on a folder or a file, a fresh map is served without an LLM call, editing one file sends only that file in full, a regeneration writes the new hashes, and deep changes or a new folder never invalidate the root map or a neighbour's.
