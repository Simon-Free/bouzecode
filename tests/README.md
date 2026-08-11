# tests/

## Purpose

Root of the pytest suite (`testpaths = ["tests"]`). It holds the shared harness — fake
LLMs, a mock streaming API server, the conversation driver — a few engine-level tests,
and four subtrees carrying the bulk of the suite.

Two invariants are enforced from here for every test in the repo: no test reaches the
live LLM API, and no test writes into the git-tracked working tree. Both are autouse
fixtures in `conftest.py`, which also tags each test `backend` / `ui` / `web` from the
folder it lives in.

`--import-mode=importlib` plus an unbroken chain of `__init__.py` gives every test module
a fully-qualified dotted name, so two same-named test files cannot shadow each other.
Adding a test directory therefore means adding its `__init__.py`.

## Usage

Harness and fixtures:

- `__init__.py` explains the `__init__.py`-chain requirement and the test that enforces it.
- `conftest.py` — loads `.env`; autouse `_llm_network_guard` (gates `stream_anthropic`
  behind `require_api_key()`), `_repo_working_tree_untouched`, `_isolate_global_state`,
  `_disable_web_ipc`; the `agent_cwd` fixture; per-folder marker tagging.
- `repo_tree_guard.py` — `tracked_root_files`, `watched_paths`, `snapshot`, `revert`:
  detects and undoes any write a test makes to this checkout.
- `fake_llm.py` — `MockLLM`, streams canned text with XML tool_use blocks through the
  real `XmlToolStreamParser`.
- `e2e_harness.py` — `bouzecode()` multi-turn conversation driver plus `TurnResult` and
  `ConversationResult`.
- `mock_anthropic_server.py` — `create_mock_anthropic_app`, `start_mock_anthropic`: a
  local SSE streaming endpoint with configurable responses that records its requests.
- `fake_mcp_server.py` — `handle_request`, `make_response`, `make_error`: a stdio
  JSON-RPC MCP server used as a subprocess target.
- `cache_conversation_helpers.py` — `require_api_key`, `wait_mcp_ready`,
  `run_turn_via_dispatch`, `call_anthropic_direct`, `dump_system_blocks` for the opt-in
  live-API tests.
- `methodology_cache_e2e_helpers.py` — `capture`, `StreamCapture`, `assert_mirrors`,
  `find_methodology_block`, `first_byte_diff`, `assert_block_byte_identical`.

Standalone scripts, run as `python tests/<file>.py` (no `test_` prefix, so pytest does
not collect them):

- `e2e_checkpoint.py` — full checkpoint story: snapshots, edits, rollback, deletion.
- `e2e_commands.py` — `/init`, `/export`, `/copy`, `/status` over a temp directory.
- `e2e_compact.py` — the `/compact` command and the compaction helpers.
- `e2e_plan_mode.py` — plan-mode permissions: reads allowed, writes blocked outside the plan file.
- `e2e_plan_tools.py` — `EnterPlanMode` / `ExitPlanMode` behaviour.

Collected tests:

- `test_context_gc.py` — context GC helpers: anchor finding, snippet trimming, GC state.
- `test_skills.py` — skill parsing, loading, argument substitution, trigger matching.
- `test_task.py` — task CRUD, task types, persistence, concurrency.
- `test_xml_docs.py` — `build_tool_docs` produces the XML tool protocol for system prompts.
- `test_xml_serializer.py` — XML serialization and round-trip parsing of calls and results.
- `test_e2e_folder_desc.py` — the `folder_desc` tool: listing, depth, symbols, errors.
- `test_e2e_html_renderer.py` — session JSON to blocks to rendered HTML.
- `test_mcp_e2e.py` — MCP initialize, `/mcp` listing, tool call inside a conversation.
- `test_proactive_e2e.py` — proactive sentinel: watcher loop, `cmd_proactive`, callbacks.
- `test_telegram_e2e.py` — the `/telegram` command against a fake Bot API.
- `test_voice_e2e.py` — the `/voice` command with STT and recorder faked out.
- `test_trivial_runner.py`, `test_trivial_runner_slow.py` — always-passing and
  deliberately slow targets used as fixtures by the test-runner tests; both are excluded
  from the main run by `collect_ignore`.

## Subfolders

| Folder | Description |
|--------|-------------|
| `backend/` | The agent engine: loop, providers, tools, prompts, skills, compaction, plan mode, conformity guards. Largest subtree. |
| `e2e/` | Feature-level end-to-end tests for plugins, skills, tasks and memory. |
| `ui/` | Terminal UI: CLI entry points, tool display and replay, paste input. |
| `web_v2/` | Second tree of Flask web-UI tests, focused on orchestration services. |
