# agent/

The agent package implements the core turn loop: stream LLM → execute tools → append results → loop until done.

---

## Entry Points

| Function | File | Description |
|----------|------|-------------|
| `run()` | `loop.py` | Main generator — one full conversation turn cycle |
| `resume_paused()` | `loop.py` | Resume after `AskUserQuestion` or `WritePlan` validation pause |

---

## Main Call Graph — `run()`

```
run(user_message, state, config, system_prompt, depth, cancel_check)
 │
 ├─ [if user_message is None]
 │   ├── _resolve_pending_from_state(state)              [loop.py]
 │   └── _complete_pending_tool_calls(pending, state, config)  [loop.py]
 │        ├── _check_permission(tc, config)              [permissions.py]
 │        ├── PermissionRequest → yield                  [state.py]
 │        ├── _propagate_denials(tcs, map, denied)       [permissions.py]
 │        ├── _build_dag_levels(permitted_tcs)           [dag.py]
 │        └── _execute_level(level, results, durations)  [dag.py]
 │
 ├─ [setup]
 │   ├── append_user_msg_to_methodology()         [context_manager.methodology]
 │   ├── _get_bouzecode_commit()                  [loop.py]
 │   ├── mcp.tools.wait_ready()                   [mcp/tools.py]
 │   └── LoopContext(...)                         [loop_context.py]
 │        └── ToolCallLoopDetector()              [loop_detector.py]
 │
 └─ while True:
     │
     ├── stream_llm_turn(state, config, system_prompt, ctx, cancel_check)
     │    → [see Zoom: stream_llm_turn]
     │
     ├── uniquify_tool_call_ids(at.tool_calls, state)    [id_uniquify.py]
     │    → yield ToolIdRemap(remap)                     [providers]
     │
     ├── estimate_tokens() → compaction_log              [compaction.py]
     │
     ├── state.messages.append(assistant msg)
     │   → yield TurnDone(tokens...)                     [state.py]
     │
     ├── [if no tool_calls]
     │    └── handle_no_tools(state, config, ctx)
     │         → [see Zoom: handle_no_tools]
     │
     ├── enforce_methodology(tool_calls, state, config, ctx)
     │    → [see Zoom: enforce_methodology]
     │
     ├── execute_tool_calls(tool_calls, state, config, ctx)
     │    → [see Zoom: execute_tool_calls]
     │
     ├── yield CheckpointReady(len(state.messages))      [state.py]
     │
     └── [if ctx.partial_stream] break
```

---

## Zoom: `stream_llm_turn()` — `loop_turn.py` L59-163

Streams one LLM call, collects timing metrics, detects thinking discipline violations.

```
stream_llm_turn(state, config, system_prompt, ctx, cancel_check)
 │
 ├── build_messages_for_api(state, config)         [minimal_payload.py]
 ├── dump_turn_payload(state, session_id, msgs)    [payload_dump.py]
 │    └── _payload_dir(session_id)                 [payload_dump.py]
 │
 ├── [if enforcement_retries > 0] filter schemas to Methodology+Snippet only
 │    └── get_tool_schemas()                       [tool_registry.py]
 │
 ├── _interruptible_iter(stream(...), cancel_check)  [loop_turn.py L25-56]
 │    ├── providers.stream(model, system, messages, tool_schemas, config)
 │    │    → yields StreamStarted, TextChunk, ThinkingChunk, ToolCallParsed, AssistantTurn
 │    └── [on cancel] raise _CancelledTurn         [loop.py]
 │
 ├── [timing computation: ttft, thinking_dur, streaming_dur, tokens/sec]
 │   → state.timing_entries.append(...)
 │
 └── [if thinking_parts]
      └── ThinkingDisciplineMonitor().analyze(text)  [thinking_parser.py]
           → state.thinking_log.append(violations)
```

---

## Zoom: `handle_no_tools()` — `loop_turn.py` L166-185

Decides what to do when the LLM produced text but no tool calls.

```
handle_no_tools(state, config, ctx) → TurnAction
 │
 ├── [if stop_reason == "max_tokens"]
 │    → inject "continue" system message → CONTINUE
 │
 ├── [if required_tool not called + nudge budget]
 │    → inject nudge message → CONTINUE
 │
 ├── [if test enforcement not done]
 │    └── check_test_enforcement(state, config)    [tools/enforcement_hooks.py]
 │         → inject warning → CONTINUE (or mark done)
 │
 └── → BREAK (end of conversation)
```

---

## Zoom: `enforce_methodology()` — `loop_turn.py` L188-239

Pre-execution enforcement: blocks tool execution if Methodology/Snippet compliance is missing.

```
enforce_methodology(tool_calls, state, config, ctx) → yields EnforcementWarning
 │
 ├── deduplicate tool_calls by ID
 ├── get_unsnippeted_reads(state.messages)          [tools/enforcement_hooks.py]
 ├── check_enforcement(tool_calls, unsnippeted)     [tools/enforcement_hooks.py]
 │
 ├── [if already retried + model complied] → clear warning
 │
 ├── [if warning + retries < MAX(2) + not all end-tools]
 │    ├── yield EnforcementWarning(missing_tools)   [loop_detector.py]
 │    ├── inject thinking + warning into messages
 │    ├── ctx.blocked_tool_calls.extend(...)
 │    └── ctx.action = CONTINUE (retry LLM call)
 │
 └── [else: passed]
      ├── merge blocked_tool_calls if any
      ├── ctx.enforcement_retries = 0
      └── ctx._final_tool_calls = deduped list
```

---

## Zoom: `execute_tool_calls()` — `loop_turn.py` L242-392

Permissions check, DAG-based parallel execution, result reporting, pause handling, loop detection.

```
execute_tool_calls(tool_calls, state, config, ctx)
 │
 ├── for each tc:
 │    ├── yield ToolStart(name, input, tool_id)         [state.py]
 │    ├── _check_permission(tc, config)                 [permissions.py]
 │    │    ├── [plan mode] check file_path vs plan_file
 │    │    ├── [auto mode] allow reads, check bash safety
 │    │    │    └── _is_safe_bash(command)              [tools/__init__.py]
 │    │    └── [manual mode] always deny
 │    ├── [if denied] yield PermissionRequest(desc)     [state.py]
 │    │    └── _permission_desc(tc)                     [permissions.py]
 │    └── build permitted_map + denied_results
 │
 ├── _propagate_denials(tool_calls, permitted_map, denied_results)  [permissions.py]
 │    → cascade denials to dependents via depends_on graph
 │
 ├── _build_dag_levels(permitted_tcs)                   [dag.py]
 │    → [see Zoom: DAG]
 │
 ├── [if web IPC active] detect AskUserQuestion tc
 │    └── is_web_ipc_active()                           [tools/interaction.py]
 │
 ├── [if no AskUserQuestion]
 │    ├── for each level: _execute_level(...)           [dag.py]
 │    ├── [check _plan_needs_validation flag]
 │    └── [on PlanRejected] cancel remaining tcs        [tools/plan_mode.py]
 │
 ├── [if AskUserQuestion found]
 │    ├── _compute_downstream(deps, {ask_tc_id})        [dag.py]
 │    └── execute only non-downstream levels
 │
 ├── for each resolved tc:
 │    ├── state.timing_entries.append(...)
 │    ├── state.messages.append(tool result)
 │    └── yield ToolEnd(name, result, permitted, dur)   [state.py]
 │
 ├── [Plan validation pause]
 │    └── raise PausedForInput(is_plan_validation=True) [tools/interaction.py]
 │
 ├── [AskUserQuestion pause]
 │    └── raise PausedForInput(question, options, ...)  [tools/interaction.py]
 │
 ├── [if all tools are end-turn tools]
 │    ├── ends_turn(name)                               [tool_registry.py]
 │    ├── [nudge if required_tool missing]
 │    └── ctx.action = BREAK
 │
 └── [loop detection]
      ├── ctx.loop_detector.record_turn(tool_calls)     [loop_detector.py]
      ├── ctx.loop_detector.check()                     [loop_detector.py]
      │    └── _turn_signature(tool_calls)              [loop_detector.py]
      ├── [if loop] inject warning + yield LoopWarning  [loop_detector.py]
      └── ctx.loop_detector.reset()
```

---

## Zoom: `resume_paused()` — `loop.py` L218-281

Resumes execution after a user answered `AskUserQuestion` or validated/rejected a plan.

```
resume_paused(pending, answer, state, config, system_prompt, cancel_check)
 │
 ├── [if plan validation]
 │    ├── is_plan_approved(answer)                  [tools/plan_validation.py]
 │    ├── [if rejected] cancel pending tcs + yield ToolEnd
 │    │    └── run(None, ...) → restart loop
 │    └── [if approved] to_run = pending_tcs
 │
 ├── [if AskUserQuestion]
 │    ├── append tool result to messages
 │    ├── append_ask_user_question_to_methodology() [context_manager/methodology.py]
 │    ├── yield ToolEnd("AskUserQuestion", ...)
 │    └── to_run = remaining pending_tcs
 │
 ├── [execute to_run]
 │    ├── yield ToolStart(...) for each
 │    ├── _build_dag_levels(to_run)                 [dag.py]
 │    ├── _execute_level(level, ...)                [dag.py]
 │    └── yield ToolEnd(...) for each
 │
 ├── yield CheckpointReady(...)
 └── run(None, state, config, system_prompt)  → continue loop
```

---

## Zoom: DAG — `dag.py`

Builds a topological ordering of tool calls from `depends_on` + implicit deps, then executes level-by-level.

```
_build_dag_levels(tool_calls) → (levels, deps)
 │
 ├── _build_alias_map(tool_calls)
 │    → {alias: tc_id} from tool_call_alias params
 │
 ├── resolve depends_on: alias → tc_id
 │    └── _coerce_list(val) — parse JSON/comma/string → list
 │
 ├── _add_implicit_write_deps(tool_calls, deps)
 │    → sequential ordering for Write/Edit to same file
 │
 ├── _inject_write_bash_deps(tool_calls, deps, alias_to_id)
 │    → auto-dep Bash on Write if command references written filename
 │
 └── topological sort → levels (list of lists)

_execute_level(level, results, durations, config)
 │
 ├── [if single tc] execute_tool() directly         [tools/__init__.py]
 │
 ├── split: parallel (is_concurrent_safe) vs sequential
 │    └── is_concurrent_safe(name)                  [tool_registry.py]
 │
 ├── _run_parallel(parallel_tcs, results, durations, config)
 │    └── ThreadPoolExecutor(max_workers=N)
 │         └── execute_tool(name, input, "accept-all", None, config)
 │
 └── sequential: execute_tool() one by one

_compute_downstream(deps, seed_ids) → set[str]
 → transitive closure of dependents (used to skip AskUserQuestion deps)
```

---

## Zoom: `uniquify_tool_call_ids()` — `id_uniquify.py`

Prevents ID collisions when the LLM reuses short IDs across turns.

```
uniquify_tool_call_ids(tool_calls, state) → remap dict
 │
 ├── _collect_used_ids(state)
 │    → scan all messages for existing tool_call IDs
 │
 ├── for each tc with colliding ID:
 │    └── _pick_fresh_id(original, turn, used)
 │         → "t{turn}_{original}" (+ _N suffix if still taken)
 │
 └── rewrite depends_on references in-place
      └── _coerce_list(depends_on)                  [dag.py]
```

---

## Zoom: `ToolCallLoopDetector` — `loop_detector.py`

Detects when the LLM repeats the same tool call pattern N times in a row.

```
ToolCallLoopDetector(max_cycle_size=8, min_repeats=3)
 │
 ├── record_turn(tool_calls)
 │    └── _turn_signature(tool_calls)
 │         → MD5 hash of sorted {name + key inputs} (SIGNATURE_KEYS)
 │
 ├── check() → LoopWarning | None
 │    → sliding window: for cycle_size 1..8, check if tail == repeated pattern
 │
 ├── record_and_check(tool_calls) → LoopWarning | None
 │    → record + check in one call
 │
 └── reset() — clear history after loop handled
```

---

## Module Reference

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | — | Re-exports: `AgentState`, `run`, `resume_paused`, events, DAG helpers |
| `state.py` | 65 | `AgentState` dataclass + event types: `ToolStart`, `ToolEnd`, `TurnDone`, `PermissionRequest`, `CheckpointReady` |
| `loop.py` | 281 | Orchestrator: `run()`, `resume_paused()`, `_complete_pending_tool_calls()`, `_resolve_pending_from_state()`, `_get_bouzecode_commit()`, `_CancelledTurn` |
| `loop_context.py` | 32 | `LoopContext` dataclass (mutable per-loop state) + `TurnAction` enum (CONTINUE/BREAK/PROCEED) |
| `loop_turn.py` | 392 | Extracted loop body: `_interruptible_iter()`, `stream_llm_turn()`, `handle_no_tools()`, `enforce_methodology()`, `execute_tool_calls()` |
| `dag.py` | 224 | DAG construction + execution: `_coerce_list()`, `_build_alias_map()`, `_build_dag_levels()`, `_compute_downstream()`, `_add_implicit_write_deps()`, `_inject_write_bash_deps()`, `_execute_level()`, `_run_parallel()` |
| `permissions.py` | 83 | `_check_permission()`, `_permission_desc()`, `_propagate_denials()` |
| `id_uniquify.py` | 71 | `_collect_used_ids()`, `_pick_fresh_id()`, `uniquify_tool_call_ids()` |
| `loop_detector.py` | 100 | `_turn_signature()`, `ToolCallLoopDetector` class, `LoopWarning` / `EnforcementWarning` dataclasses |
| `payload_dump.py` | 37 | `_payload_dir()`, `dump_turn_payload()` — JSONL debug trace |

---

## External Dependencies (called from agent/)

| Module | Functions used |
|--------|---------------|
| `providers` | `stream()`, `AssistantTurn`, `TextChunk`, `ThinkingChunk`, `ToolCallParsed`, `ToolIdRemap`, `StreamStarted` |
| `tool_registry` | `get_tool_schemas()`, `ends_turn()`, `is_concurrent_safe()`, `get_tool()` |
| `tools/__init__` | `execute_tool()`, `_is_safe_bash()` |
| `tools/interaction` | `PausedForInput`, `is_web_ipc_active()` |
| `tools/plan_mode` | `PlanRejected` |
| `tools/plan_validation` | `is_plan_approved()` |
| `tools/enforcement_hooks` | `check_enforcement()`, `get_unsnippeted_reads()`, `check_test_enforcement()` |
| `minimal_payload` | `build_messages_for_api()` |
| `compaction` | `estimate_tokens()` |
| `thinking_parser` | `ThinkingDisciplineMonitor` |
| `context_manager/methodology` | `append_user_msg_to_methodology()`, `append_ask_user_question_to_methodology()` |
| `mcp/tools` | `wait_ready()` |
| `config` | `CONFIG_DIR` |
