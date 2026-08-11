# agent_loop/

## Purpose
Tests of the conversational turn loop of `bouzecode.backend.agent` — when a turn
continues, when it is nudged, and when the session closes. Most files script a whole
conversation through the `bouzecode()` harness (`tests/e2e_harness`) fed by a
`MockLLM` (`tests/fake_llm`) and assert on the resulting `AgentState`; the rest are
pure unit tests over a single module (`loop_detector`, `thinking_parser`,
`snippet_wire`, `stream_interceptor`, `close_validator`).

## Usage

Closing the session:
- `test_final_answer_e2e.py` — FinalAnswer closes the session; a validator refusal or an empty answer keeps it running.
- `test_close_requires_final_answer.py` — `close_requires_final_answer` mode: headless text without tools does not close, FinalAnswer does, thinking-only is nudged toward implementing, and the nudge cap never bricks the session.
- `test_close_requires_recap.py` — `close_validator.missing_recap_sections`, `missing_recap_fields` and `validate_close`: the six-section recap gate runs before any LLM validation, with a retry cap.
- `test_recap_json_string_coercion.py` — `tools.registration._coerce_recap` and `_final_answer`: a recap handed over as a JSON string is reparsed into a dict for both the gate and persistence.
- `test_close_over_failed_tool_e2e.py` — a FinalAnswer emitted beside a refused tool does not close; beside a successful one it does; repeated tool failure still terminates with an explicit close reason.
- `test_context_only_final_answer.py` — a Methodology/Snippet-only batch is nudged instead of closing, while adding a real tool keeps the loop going.

Meta-only and empty turns:
- `test_meta_only_continue_e2e.py` — a silent Methodology-only turn continues the session, three consecutive ones terminate it, and a working turn resets the counter.
- `test_meta_only_progress_aware.py` — consecutive meta-only turns close only once they stop bringing anything new; a backstop terminates endless note-taking.
- `test_meta_only_counter_t102.py` — the `state.meta_only_nudges` telemetry counter increments once per injected nudge.
- `test_empty_turn_continuation_e2e.py` — an empty reply after a Methodology-carrying batch gets a capped continuation nudge rather than a session-closing compliance bounce.
- `test_readonly_nudge.py` — exploration-only streak nudge and abort; module-level skip, the streak being tracked for observability only.

Stream robustness:
- `test_partial_stream_recovery.py` — a stream dying after some `ToolCallParsed` events still yields a synthetic `AssistantTurn`, executes the parsed tools and checkpoints; drives `loop.run` with hand-built provider events.
- `test_swallowed_tooluse_recovery.py` — a `<tool_use>` swallowed by a code fence or by `<thinking>` is re-prompted instead of closing the session.
- `test_stream_interceptor.py` — `stream_interceptor.set_stream_interceptor` and `get_streamer`: the interceptor sees the main turn and the enforcement side-call, `None` restores the default, and harness monkeypatching still composes.

Loop internals and wiring:
- `test_loop_subdivision.py` — `loop_context.LoopContext` defaults and `TurnAction`, plus a smoke run of `loop.run` across the sub-modules.
- `test_enforcement_persist.py` — a missing Methodology is stored as a dedicated `role="enforcement"` message placed before the assistant turn.
- `test_loop_detector.py` — `thinking_parser.LoopDetector`: catches repeated blocks, no false positive on analytical text, code analysis or tables, incremental feeding, minimum pattern size.
- `test_tool_loop_detector.py` — `loop_detector.ToolCallLoopDetector`: cycle detection, reset, multi-tool turns, edge cases.
- `test_snippet_wire_file.py` — `snippet_wire.is_file_snippetable`, `wrap_file_snippetable`, `is_snippetable_tool_id`, `wrap_snippetable` and `SNIPPET_MIN_LINES`.
- `test_artifacts_wiring.py` — `AgentState.artifacts` is per-session, and the loop gives tools a config whose `artifacts` IS `state.artifacts`; probed with a throwaway registered tool so no plugin is required.
- `test_classification_e2e.py` — task classification routes to the profile that actually reaches the wire in the system prompt; skipped on Windows, where the mock-api streaming harness hangs.

## Subfolders
| Folder | Description |
|--------|-------------|
| `turn/` | Inside a single turn: interruption, truncated stream, end-of-turn detection. |
| `e2e/` | Whole conversations through the harness: real LLM, scripted mock, token optimizations. |
