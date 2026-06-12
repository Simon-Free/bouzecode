# MR1 Migration Notes — Engine Port

## What Was Ported

### `src/bouzecode/backend/` (full internal engine)
- `agent/` — loop, loop_turn, state, hooks, enforcement, close_validator, providers (anthropic_stream, openrouter, dispatch, types)
- `checkpoint/` — hooks, store, types
- `commands/` — dispatcher + core/, extensions/, info/, misc/, session/, proactive, image_cmd, worker, ssj, telegram_cmd, plan_cmd
- `commands/oss_shims/` — NEW: wires flat-package features into the new dispatcher
- `context_manager/` — methodology, notes, snippet_resolve, state
- `core/` — config, context, paths, tool_registry, _embedded_data
- `data/` — logo.txt, static assets
- `multi_agent/` — definitions, manager, subagent, task, terminal, tools
- `profiles/` — composer, loader, models
- `tools/` — ops/, skill/, task/, folder_desc/, registration, schemas, interaction, enforcement_hooks
- `xml_tool_protocol/` — parser, serializer, docs

### `src/bouzecode/ui/` (terminal UI)
- cli.py, repl.py, ansi.py, rendering.py, spinner.py, tool_display.py, replay.py, repl_sentinels.py, paste_input/

### `src/system_prompts/` (profile prompts)
- All 8 prompt files from internal source

### Test Infrastructure
- `tests/fake_llm.py` — MockLLM (streams XML through XmlToolStreamParser)
- `tests/e2e_harness.py` — `bouzecode()` multi-turn test runner with mock patching
- `tests/mock_anthropic_server.py` — Flask SSE mock for wire-level tests
- `tests/cache_conversation_helpers.py` — LIVE_API_ALLOWED guard, require_api_key()
- `tests/conftest.py` — .env loader, LLM network guard, global state isolation, markers

### Smoke Tests
- `tests/backend/test_engine_smoke.py` — 5 tests: multi-turn, tool exec, FinalAnswer, thinking, parallel tools
- `tests/backend/test_shims_smoke.py` — 7 tests: all OSS shim imports + callability

### OSS Feature Shims (wired in dispatcher)
| Command | Flat Package | Shim |
|---------|-------------|------|
| `/voice` | `voice/` | `oss_shims/voice_cmd.py` |
| `/video` | `voice/` (video mode) | `oss_shims/video_cmd.py` |
| `/mcp` | `mcp/` | `oss_shims/mcp_cmd.py` |
| `/plugin` | `plugin/` | `oss_shims/plugin_cmd.py` |
| `/memory` | `memory/` (flat module) | `oss_shims/memory_cmd.py` |

## Extensibility — Plugin / Skill / Task / Memory (MR6)

### Registry Unification Policy

The OSS repo has **two** tool registry lineages:
1. **Root `tool_registry.py`** — standalone dict, used by flat packages (`memory/`, `plugin/`).
2. **Backend `src/bouzecode/backend/core/tool_registry.py`** — engine registry with thread-local overlays, disable/enable.

**Decision:** Root `tool_registry.py` is now a **thin re-export shim** that delegates entirely to the backend registry. Any flat package importing `from tool_registry import register_tool` now registers directly into the engine's canonical store.

### Doublon Resolution — Who Wins?

| Feature | Backend (`tools/`) | Flat package | Winner |
|---------|-------------------|--------------|--------|
| Skill   | `tools/skill/` (loader, tools, builtin) | — | **Backend** (LLM tools: Skill, SkillList) |
| Task    | `tools/task/` (store, tools, types) | — | **Backend** (LLM tools: TaskCreate, TaskUpdate, TaskGet, TaskList) |
| Memory  | — (no backend equivalent) | `memory/` (store, tools, context, scan) | **Flat package** via registry shim |
| Plugin  | — (no backend equivalent) | `plugin/` (store, loader, types, recommend) | **Flat package** via registry shim |

### Slash Commands (OSS Shims)

`/plugin` and `/memory` are **slash commands** (user-typed, NOT LLM tools). They live in `oss_shims/` and delegate to the flat packages:
- `/plugin list|install|uninstall` → `plugin.store.list_plugins`, `plugin.store.install_plugin`, etc.
- `/memory [query]` → `memory.store.load_entries`, `memory.context.find_relevant_memories`

### LLM Tools — DEFAULT_ENABLED

The following tools are enabled by default for the model:
- **Skill/Task:** `Skill`, `SkillList`, `TaskList` (TaskCreate/Update/Get available but disabled)
- **Memory:** `MemorySave`, `MemoryList` (MemoryDelete/Search available but disabled)
- **Plugin:** Plugin tools registered dynamically via `register_plugin_tools()`

### Test Strategy

All e2e tests use `MockLLM` (no network). Features tested:
- Skill execution with custom `.md` skill file
- Task create → list → done lifecycle
- Memory save → list → verify persistence
- Plugin discovery + tool registration from fake plugin in tmp_path

## Collision Resolution

- `bouzecode.py` (flat module) → renamed to `bouzecode_legacy.py`
- `src/bouzecode/__init__.py` provides backward-compatible `__getattr__` for:
  - `VERSION`, `C`, `clr`, `info`, `ok`, `warn`, `err` (from `ui.ansi`)
  - `stream_text`, `stream_thinking`, `flush_response` (from `ui.rendering`)
  - `main()` (from `ui.cli`)
  - `cmd_*`, `handle_slash`, `COMMANDS` (from `backend.commands.dispatcher`)
  - `strip_unpaired_surrogates` (inline fallback)
- Entry point `bouzecode` → `bouzecode:main` resolves to new package

## Pre-Existing Test Failures (NOT caused by this MR)

| Test | Failure | Root Cause |
|------|---------|------------|
| `tests/test_plugin.py::TestAskUserQuestion::test_roundtrip_with_freetext` | `PausedForInput` raised | Flat `tools.interaction` raises instead of returning — test needs mock |
| `tests/test_plugin.py::TestAskUserQuestion::test_roundtrip_with_option_selection` | `PausedForInput` raised | Same as above |
| `tests/test_xml_docs.py::test_docs_include_a_parsable_xml_example` | No parsable example found | Flat `xml_tool_protocol.build_tool_docs` doesn't embed a `<tool_use>` example block |

## What Is NOT Ported (left for future MRs)

| Item | Reason |
|------|--------|
| `web_v2/` | Parallel MR by another agent |
| `web/` (legacy Flask app) | Already exists in OSS as flat package — not touched |
| `/demo` command | No clear demo runner in flat `demos/` — deferred |
| Telegram integration | Internal `telegram_cmd.py` ported but requires `python-telegram-bot` not in deps |
| Proactive sentinel | Ported in dispatcher but `proactive/` flat package may need wiring |
| Full e2e test suite from internal | Only smoke tests ported; full backend/ test tree left for next MR |

## Package Layout After This MR

```
bouzeoss_wt_mr1/
├── src/
│   ├── bouzecode/          # NEW — full engine package
│   │   ├── __init__.py     # backward-compat + main()
│   │   ├── __main__.py     # python -m bouzecode
│   │   ├── backend/        # agent, commands, core, tools, ...
│   │   └── ui/             # cli, repl, ansi, rendering, ...
│   └── system_prompts/     # NEW — profile prompt files
├── tests/
│   ├── conftest.py         # NEW — guards + isolation
│   ├── fake_llm.py         # NEW — MockLLM
│   ├── e2e_harness.py      # NEW — bouzecode() test runner
│   ├── mock_anthropic_server.py  # NEW — SSE mock
│   ├── cache_conversation_helpers.py  # NEW — live API helpers
│   └── backend/
│       ├── test_engine_smoke.py   # NEW — 5 engine tests
│       └── test_shims_smoke.py    # NEW — 7 shim tests
├── agent/                  # EXISTING flat packages (untouched)
├── commands/
├── voice/
├── mcp/
├── plugin/
├── ...
├── bouzecode_legacy.py     # RENAMED from bouzecode.py
└── pyproject.toml          # UPDATED for src layout coexistence
```

## Validation

```
554 passed, 3 failed (pre-existing), 1 warning
0 network calls (LLM guard active)
Runtime: ~7s
```
