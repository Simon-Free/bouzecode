# enforcement/

## Purpose
Tests of the working-memory enforcement path: `agent.loop_turn.enforce_methodology`,
the forced side-calls in `agent.enforcement_call` (`recover_methodology`,
`recover_snippets`, `snippetable_results`), the wire markers in `agent.snippet_wire`,
the coverage scan in `tools.enforcement_hooks`, and what `agent.minimal_payload` keeps
of an enforcement exchange. Side LLM calls are replaced by monkeypatched stand-ins, so
nothing here reaches the network.

## Usage
- `test_enforcement_cache_stability.py` — `stream_llm_turn` sends the full `get_tool_schemas()` even when `ctx.enforcement_retries > 0`, so the cached tool docs stay byte-identical.
- `test_enforcement_recovery.py` — `enforce_methodology` dedups and proceeds; `recover_methodology` / `recover_snippets` seed their side-call from the previous note, the turn's thinking and the executed results, and the loop prepends or appends the recovered calls to the batch before it runs.
- `test_minimal_payload_enforcement.py` — `build_minimal_payload` drops the assistant batch but keeps the injected enforcement user message.
- `test_recovery_best_effort.py` — a side-call raising `RecoveryFailed` must not kill the conversation.
- `test_reemit_after_swallowed_batch.py` — a turn with no tool calls closes the session instead of bouncing in-wire, and `check_enforcement` reports only what was really called.
- `test_snippet_full_context.py` — the snippet side-call is handed the user prompt, the note, the thinking and the complete tool results, untruncated.
- `test_snippet_threshold.py` — `SNIPPET_MIN_LINES` applied consistently by `wrap_snippetable`, `wrap_file_snippetable`, `get_unsnippeted_reads` and `snippetable_results`.

## Subfolders
| Folder | Description |
|--------|-------------|
| `e2e/` | The same enforcement seen from real conversations. |
