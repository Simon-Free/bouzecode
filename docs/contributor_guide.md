# Contributor Guide: Where to Change What in bouzecode

This guide is for contributors implementing new features or updating existing behavior.
It focuses on **which files matter**, **how data flows**, and **how to make safe changes quickly**.

All paths below are relative to `src/bouzecode/` unless stated otherwise.

---

## 1) Fast mental model

If you remember only one thing, remember this flow:

1. `ui/cli.py` parses the command line; `ui/repl.py` runs the interactive loop.
2. `backend/commands/dispatcher.py` owns the `COMMANDS` table and routes every slash command.
3. `backend/core/context.py` assembles the system prompt from the fragments in `src/system_prompts/`.
4. `backend/agent/loop.py` + `loop_turn.py` run the turn loop; `backend/agent/dag.py` executes the tool batch of a turn as a dependency graph.
5. `backend/agent/providers/registry.py` maps a model string to a provider and an API model id; `providers/backends/` holds the streaming clients.
6. `backend/core/tool_registry.py` is the single source of truth for callable tools; `backend/tools/registration.py` is where everything gets registered.
7. Feature packages plug into that loop — some inside the engine (`backend/multi_agent/`, `backend/checkpoint/`, `backend/plugin/`, `backend/tools/skill/`, `backend/tools/task/`), some as flat top-level packages (`memory/`, `mcp/`, `voice/`, `video/`, `plugin/`).

---

## 2) Core files you should read first

### Runtime + UX shell
- `ui/cli.py` — entry point (`main()`), argument parsing, ripgrep bootstrap, version switching.
- `ui/repl.py` — the interactive loop, permission prompts, diff rendering.
- `ui/rendering.py`, `ui/tool_display.py`, `ui/ansi.py` — everything printed to the terminal.
- `backend/commands/dispatcher.py` — `COMMANDS`, `_CMD_META`, `handle_slash()`. Add or change slash commands here.

### Agent execution loop
- `backend/agent/loop.py` and `loop_turn.py` — the heart of the app: stream model output, execute the tool batch, append results, continue.
- `backend/agent/dag.py` — builds a dependency graph from the `depends_on` declarations and runs tools level by level, in parallel within a level.
- `backend/agent/permissions.py` — the permission gate.
- `backend/agent/close_validator.py`, `close_guard.py` — the conditions under which a turn is allowed to end.
- `backend/agent/enforcement_call.py` — the side-calls that recover a missing `Methodology` entry or an un-snippeted read.

### Tool system
- `backend/core/tool_registry.py` — `ToolDef`, `register_tool`, `FRAMEWORK_ALWAYS_ON`, the enable/disable state and the centralized `execute_tool` dispatch with output truncation.
- `backend/tools/schemas.py` — the JSON schemas of the core built-in tools.
- `backend/tools/ops/` — their implementations, one concern per file (`file_ops.py`, `shell_search.py`, `web_ops.py`, `test_runner.py`, `diff_ops.py`, …).
- `backend/tools/registration.py` — where the schemas are bound to implementations, where the side-effect imports pull in the other packages' tools, and where the default whitelist pass runs.

### Model providers, prompt, compaction
- `backend/agent/providers/registry.py` — `PROVIDERS`, `resolve_provider()`, model aliases, `COSTS`, retry settings.
- `backend/agent/providers/backends/` — the Anthropic and OpenRouter transports, native and XML tool paths.
- `backend/core/context.py` and `src/system_prompts/` — system prompt assembly.
- `backend/agent/compaction.py` and `backend/context_manager/` — the methodology note, snippets, notes, and the compaction layers.
- `backend/core/config.py` — defaults and persistent config handling.

### Web UI
- `web_v2/app.py` — app factory, the `/api/schema` derivation from the URL map, `main()`.
- `web_v2/routes/` — HTTP surface, one blueprint per area.
- `web_v2/services/` — the logic, deliberately Flask-free so it can be tested on its own.
- `web_v2/runtime/` — agent lifecycle: `runner.py`, `ipc.py`, `warmpool.py`, `venv_env.py`, the context viewer and the HTML renderer.

---

## 3) Feature packages: exact entrypoints

### Memory (`memory/`, top-level)
- `memory/tools.py` — the `MemorySave` / `MemoryList` / `MemorySearch` / `MemoryDelete` tools. Imported for its side effects by `backend/tools/registration.py`.
- `memory/store.py` — persistence and indexing rules.
- `memory/context.py` — retrieval and ranking of what gets injected into the prompt.
- `memory/scan.py`, `memory/consolidator.py` — metadata scanning and consolidation.
- Command wiring: `backend/commands/oss_shims/memory_cmd.py`.

### MCP (`mcp/`, top-level)
- `mcp/config.py` — merges `~/.bouzecode/mcp.json` (user) with the nearest `.mcp.json` walking up from `cwd` (project wins).
- `mcp/stdio_transport.py`, `mcp/http_transport.py`, `mcp/client.py` — transports and JSON-RPC.
- `mcp/tools.py` — `initialize_mcp()` connects the servers and registers the discovered tools. Called at the end of `backend/tools/registration.py`, *after* the whitelist pass, so MCP tools stay enabled.
- Command wiring: `backend/commands/oss_shims/mcp_cmd.py`.

### Plugins
- `plugin/` (top-level) and `backend/plugin/` — `store.py` (install / uninstall / enable / disable / update), `loader.py` (dynamic import, `register_plugin_tools`, `register_plugin_hooks`), `recommend.py`.
- Hook registration is deliberately **deferred**: calling it from `tools/__init__` would create an import cycle. The pipeline catalog loads it lazily at agent startup.
- Command wiring: `backend/commands/oss_shims/plugin_cmd.py`.

### Sub-agents (`backend/multi_agent/`)
- `tools.py` registers `Agent`, `MessageAgent`, `SendMessage`, `CheckAgentResult`, `ListAgentTasks`, `ListAgentTypes`, `Fleet`.
- `subagent.py` and `manager.py` handle the thread pool, depth control and messaging.
- Worktree provisioning for web-launched agents lives in `web_v2/services/work/provisioning.py` and `isolation.py`.

### Skills (`backend/tools/skill/`)
- `loader.py` — discovery order and frontmatter parsing; `frontmatter.py`, `parsing.py`, `scope.py` split the details.
- `executor.py` — inline vs forked execution.
- `tools.py` — the `Skill` / `SkillList` / `SkillGrep` tool APIs.

### Tasks (`backend/tools/task/`)
- `types.py` (model + status enum), `store.py` (thread-safe CRUD, dependency edges), `tools.py` (`TaskCreate` / `TaskUpdate` / `TaskGet` / `TaskList`).

### Checkpoints (`backend/checkpoint/`)
- `types.py` (`FileBackup`, `Snapshot`), `store.py` (backup, snapshot, rewind, cleanup), `hooks.py` (intercepts `Write` / `Edit` / `NotebookEdit` to back up before modifying).
- Command wiring: `backend/commands/session/checkpoint_cmd.py` and `revert_cmd.py`.

### Navigation maps (`backend/tools/agents_map/`, `backend/tools/folder_desc/`)
- `agents_map/` — `AgentsMap` and `SymbolMap`: the per-folder map of the repository and its symbols.
- `folder_desc/` — `GetFolderDescription`: the annotated file tree, kept fresh by write hooks.

### Voice (`voice/`, top-level)
- `recorder.py` — capture backends (`sounddevice`, `arecord`, `sox`) with silence detection.
- `stt.py` — the transcription fallback chain.
- `keyterms.py` — vocabulary boosting from the repo, the branch and the open files.
- Command wiring: `backend/commands/oss_shims/voice_cmd.py`.

### Video (`video/`, top-level)
- `story.py` → `tts.py` → `images.py` → `subtitles.py` → `assembly.py`, orchestrated by `pipeline.py`.
- Command wiring: `backend/commands/oss_shims/video_cmd.py` and `video_wizard_cmd.py`.

---

## 4) "I need to implement X" → where to edit

### Add a new built-in tool
1. Add the schema to `backend/tools/schemas.py`.
2. Implement it in a focused module under `backend/tools/ops/`.
3. Bind the two with a `ToolDef` in `backend/tools/registration.py`.
4. Decide `read_only` and `concurrent_safe` correctly — the DAG executor parallelises on `concurrent_safe`, and the permission gate reads `read_only`.
5. Decide whether the tool belongs to `_DEFAULT_WORK_TOOLS` (sent to every agent) or should stay off until a profile enables it. Every schema is tokens on every turn.
6. Add a conversation test under `tests/backend/tools/`.

### Add a new slash command
1. Write the handler in the right `backend/commands/` subpackage (`core/`, `session/`, `info/`, `extensions/`, `misc/`).
2. Register it in `COMMANDS` and describe it in `_CMD_META` in `backend/commands/dispatcher.py`. Handlers take `(args, state, config)`.
3. If it wraps a flat top-level package, put the thin wrapper in `backend/commands/oss_shims/` instead.
4. Prefer putting the real logic in a tool module and calling it from the command.
5. Add a test under `tests/backend/commands/`.

### Add a model, a price, or a routing rule
1. Update `PROVIDERS`, `_MODEL_ALIASES`, `_OPENROUTER_MODELS` and `COSTS` in `backend/agent/providers/registry.py`.
2. Add a `_CACHE_READ_OVERRIDE` entry if the provider does not bill cached tokens at 0.1× input.
3. Check `resolve_provider()` still routes the bare name the way a user would type it.
4. Never hardcode a base URL: an endpoint that is not the official API belongs in an environment variable.

### Change prompt or context injection
1. Edit the fragment in `src/system_prompts/`, not the Python that concatenates it.
2. Wire it in `backend/core/context.py`; `lean_prompt.py` decides what a reduced prompt keeps.
3. Watch the size: `tests/backend/prompts/` holds conformity tests, including one that checks no prompt names a tool the agent cannot call.

### Change compaction or context pruning
1. `backend/agent/compaction.py` for the turn-level layer, `backend/context_manager/` for the methodology note, the snippets and the note blocks.
2. `backend/context_manager/compact_judge.py` decides when a deep compaction is worth its own LLM call.
3. Add or update tests under `tests/backend/compaction/` and `tests/backend/methodology/`.

### Add a built-in agent
1. Drop a YAML file in `backend/profiles/builtin/`.
2. Declare `tools:` explicitly — an empty list means *no restriction*, which is rarely what you want for a specialised agent.
3. Add a test under `tests/backend/profiles/`, and let the conformity test check that its prompt only names tools it actually holds.

### Add a web page or endpoint
1. Route in `web_v2/routes/`, logic in `web_v2/services/`. Keep Flask out of the services.
2. Do not hand-write API documentation: `/api/schema` derives it from the URL map.
3. Never make the front parse stdout — emit into the structured session JSON instead.
4. Test with the Flask test client first; reach for Playwright only when a real DOM is the only proof.

---

## 5) Tests: what to run and where to add coverage

```bash
uv pip install -e ".[test]"
python -m pytest -q                    # the whole suite
python -m pytest -q -n auto            # in parallel
python -m pytest -q -m backend         # the engine only
python -m pytest -q tests/web_v2       # the web service layer
python -m pytest -q src/bouzecode/web_v2/tests   # the tests that ship with the package
```

`testpaths` is `tests/`. Tests are auto-marked from their top-level folder: `tests/backend/` → `backend`, `tests/ui/` → `ui`, `tests/frontend/` → `web`. A `slow` marker tags the fixture files the test-runner tests target.

A hermetic guard in `tests/conftest.py` blocks any real LLM call unless a test opts in with `require_api_key()`, so a stray credential can never turn a run into a bill.

The policy lives in `tests/backend/TEST_METHODOLOGY.md`, with the per-file state in `TEST_TRIAGE.md`. In short: a test must be readable without opening the code it tests, so the suite is dominated by conversation tests driven through `tests/e2e_harness.py` and `tests/fake_llm.py`. Take the highest of the four levels that suffices: `mock_llm`, `mock_api`, Flask test client, Playwright.

Recommended workflow: run the impacted folder first, then the whole suite before opening a PR, and add at least one success-path and one failure/edge case per new capability.

---

## 6) Conventions and gotchas

- **Registry-first architecture.** If the model should be able to call it, it is a registered tool — not a branch inside the loop.
- **Import side effects matter.** `backend/tools/registration.py` imports several packages purely for their registration side effects, and the *order* matters: anything registered before the whitelist pass gets disabled unless it is in `FRAMEWORK_ALWAYS_ON` or `_DEFAULT_WORK_TOOLS`; chrome-devtools and MCP register after it on purpose.
- **Circular imports are a live hazard.** `tools/__init__` → `agent.hooks.pipeline` → `agent.__init__` → `loop` → `dag` → `tools` is a real cycle that crashes the agent subprocess. That is why plugin hook registration is deferred.
- **Every schema costs tokens on every turn.** Enabling a tool by default is a budget decision, not a convenience one.
- **The neutral message format is the internal contract.** Provider adapters must preserve tool-call ids and arguments exactly.
- **The web UI never parses stdout.** Every view is rendered from the structured session JSON, the IPC files and the payload dumps.
- **The API schema is derived, not written.** It comes from `app.url_map`.
- **Runtime state is under `~/.bouzecode/`.** Tasks, memories and sessions are home- and cwd-dependent; a test that changes directory changes their behaviour.
- **Folder maps must stay in step.** Every code folder carries a `README.md` listing its purpose and symbols. `python -m readme_sync --check` reports drift, `--list-stale` names it, `--regen` rebuilds one.

---

## 7) Suggested onboarding order

1. The root `README.md` — the user surface.
2. `ui/cli.py` and `ui/repl.py` — the runtime shell.
3. `backend/agent/loop.py` and `dag.py` — the core loop.
4. `backend/core/tool_registry.py` and `backend/tools/registration.py` — the extension spine.
5. Your target package.
6. Its `README.md`, then its tests.

---

## 8) PR checklist

- [ ] The change sits in the right layer (tool vs slash command vs provider vs service).
- [ ] Schema and implementation are both updated, and `read_only` / `concurrent_safe` are correct.
- [ ] Permission behaviour is intentional.
- [ ] Any new default-enabled tool is justified against its per-turn token cost.
- [ ] No base URL, host or credential is hardcoded.
- [ ] Tests added or updated, at the highest level that proves the behaviour.
- [ ] `python -m readme_sync --check` is clean.
- [ ] Docs updated if user-facing behaviour changed.
- [ ] No unrelated refactors mixed into the same PR.
