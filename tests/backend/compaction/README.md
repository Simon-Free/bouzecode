# compaction/

## Purpose
Tests of the two ways context is shrunk: the mechanical pass in `agent.compaction`
(token estimation, context limits, tool-result snipping, split point) and the judged
pass in `context_manager.compact_methodology.maybe_compact`, which asks a model which
`## snippet:` blocks may go. The judge is a local fake wired through
`agent.stream_interceptor.set_stream_interceptor`, so no network is involved.

## Usage
- `test_compaction.py` — `estimate_tokens`, `get_context_limit`, `snip_old_tool_results`, `find_split_point`.
- `test_note_deep_compaction.py` — `maybe_compact` triggers on the cached-prefix size, offers only older snippet blocks (never prose, decisions, the user request, the freshest snippets, or a file the agent returned to), is idempotent, spaces two passes by a break-even, journals its verdict, and leaves the note intact when the provider fails.
- `test_regen_embedded_data.py` — the main prompt lives in `src/system_prompts/` and `core._embedded_data` loads it from there.
