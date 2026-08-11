# methodology/

## Purpose
Tests of `bouzecode.backend.context_manager.methodology` — the durable working-memory
note: the `Methodology` tool, the hooks that auto-append user messages / plans /
answered questions, the per-turn journal, and the fact that the note reaches the wire.
Approach is mixed: pure unit calls on a `ContextState` for the note algebra, real
`bouzecode()` conversations (`tests.e2e_harness` + `tests.fake_llm.MockLLM`) for the
end-user behaviour, and `dispatch.stream` for the wire.

## Usage
- `test_methodology_append_only.py` — `methodology_tool` is append-only; `mode=replace` still appends and preserves prior snippets.
- `test_methodology_prompt_balance.py` — reads `src/system_prompts/`: the main prompt carries no length cap and keeps the anti-recopy rule; the XML and JSON tool-example blocks show a multi-line Methodology.
- `test_methodology_race.py` — `_append_block` under a `ThreadPoolExecutor`: concurrent read-modify-write on `context_state.notes`.
- `test_methodology_resume.py` — the note survives an `AskUserQuestion` pause/resume and is restored from the session file.
- `test_methodology_timeline.py` — `notes_timeline` records a dated delta per turn; `reconstruct_methodology_from_timeline` folds it back, including across a `compact_methodology` event.
- `test_methodology_tool.py` — append semantics plus `append_user_msg_to_methodology`, `append_plan_to_methodology`, `append_ask_user_question_to_methodology`; interleaved order is preserved.
- `test_methodology_tool_e2e.py` — the same contract driven by a mocked model in a real conversation, asserted on `result.state.context_state.notes`.
- `test_methodology_wire_transmission.py` — `dispatch.stream` yields a `SystemPayload` whose system blocks carry the note, so cross-turn context survives even though prior user messages are dropped from the message list.
- `test_timeline_delta_only.py` — the journal stores deltas only, sessions written with full snapshots still reload, and a compaction entry is a full replacement.

## Subfolders
| Folder | Description |
|--------|-------------|
| `cache/` | The A/B split of the note for Anthropic prompt caching. |
| `ends_turn/` | Whether a meta-only tool batch ends the agent turn. |
| `snippet/` | The `Snippet` tool: ranges, symbols, path fallback, enforcement. |
