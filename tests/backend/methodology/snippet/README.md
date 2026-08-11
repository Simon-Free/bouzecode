# methodology/snippet/

## Purpose
Tests of the `Snippet` tool — `context_manager.methodology.snippet_tool`,
`context_manager.snippet_resolve`, the read-file matcher in `tools.state`, and the
coverage check in `tools.enforcement_hooks`. Most scenarios are real `bouzecode()`
conversations (`tests.e2e_harness` + `MockLLM`) asserting on the resulting methodology
note; only the pure string algorithms stay at unit level.

## Usage
- `test_skill_snippet_enforcement.py` — `get_unsnippeted_reads` / `check_enforcement` treat a `Skill` result like a `Read`: uncovered triggers enforcement, Snippet or discard clears it.
- `test_snippet_e2e.py` — conversation coverage of ranges, multiple ranges, end-of-file clamping, every error path, discard, and path recovery from an earlier `Read`; also checks the note journal entry.
- `test_snippet_leniency_e2e.py` — an absent `ranges` saves the whole target whatever its size; a dead `tool_id` is refused with the live ids listed; a deleted file is reported.
- `test_snippet_no_cap_e2e.py` — a large file and a large symbol are frozen entirely, with no truncation marker.
- `test_snippet_skill_mention.py` — the main system prompt and the tool description both name `Skill` as a Snippet trigger.
- `test_snippet_symbol.py` — `resolve_snippet_symbol` (function, class method, not found, relative path, missing file) and `snippet_tool(symbol=...)` rendering through `build_methodology_system_blocks`.
- `test_snippet_tool_fallback.py` — the matcher behind path recovery: `find_closest_read_file`, `list_read_files_with_basename` (basename match, case-insensitivity, longest common suffix, refusal on a tie).
- `test_symbol_snippet_cache_stability.py` — editing a symbol-snippeted file leaves the rendered methodology block byte-identical and only appends a stale marker via `stale_hooks._mark_stale_snippets`.
- `test_tool_id_snippet_e2e.py` — a tool registered at test time produces snippetable output keyed by `tool_id`: it lands in the note, is wrapped on the wire, and enforcement fires when uncovered.
