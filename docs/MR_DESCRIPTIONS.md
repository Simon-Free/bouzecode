# MR Descriptions — bouzecode_oss Migration

## Ordre de merge recommandé

1. **MR1** — Engine Core (base, toutes les autres en dépendent)
2. **MR10** — fix(parser) thinking backticks swallow tool_use (depends on MR1)
3. **MR2** — Web V2
4. **MR3** — Voice
5. **MR4** — Video
6. **MR5** — MCP
7. **MR6** — Plugin / Skill / Task / Memory
8. **MR7** — Demos / HtmlRenderer / FolderDesc
9. **MR8** — Internal Test Suite (1200+ tests)
10. **MR9** — Telegram & Proactive
11. **Integration** — Final merge branch (1425 tests green)

> MR2–MR10 all depend on MR1 (engine-core). Merge MR1 first, then MR10 (critical parser fix), then the others in any order (recommended: numerical).

---

## MR1 — Engine Core

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr1-engine-core` |
| **Base** | `main` |
| **Title** | feat: port backend engine and UI from internal source |

### Commits
- `2aca6fb` feat: port backend/ engine from internal source
- `2e201ae` feat: port ui/ from internal source
- `0d95374` test: port e2e test infrastructure from internal
- `1ae5166` test: add engine smoke tests
- `7f43b46` docs: add MIGRATION.md
- `1675ac6` refactor: resolve bouzecode.py module/package collision
- `e827ebe` fix(xml_tool_protocol): parsable example in tool docs
- `2e3c6d0` fix(tests): web-ipc isolation for CI agent environment

### Features
- Complete backend engine (providers, agent loop, tools, sessions, DAG, methodology, etc.)
- UI layer (CLI display, paste input)
- E2E test infrastructure with conftest fixtures
- MIGRATION.md documentation

### Tests
~50 smoke + e2e tests

---

## MR2 — Web V2

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr2-web-v2` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | feat(web_v2): port web frontend/backend with full test suite |

### Commits
- `8cf6210` feat(web_v2): port source code from internal repo
- `208a987` test(web_v2): port embedded tests
- `f0b951f` test(web_v2): port external test suite
- `0af5755` chore: add conftest.py and pytest config for src-layout
- `962fcf6` fix(packaging): move [tool.pytest.ini_options] after [tool.setuptools] section
- `a370e7b` fix(tests): keep rootdir in sys.path, prioritize src/ for package resolution

### Features
- Web V2 server (FastAPI/Starlette)
- WebSocket IPC bridge
- Typologies, sessions, streaming endpoints
- Full pytest suite for web layer

### Tests
~120 tests (web_v2 specific)

---

## MR3 — Voice

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr3-voice` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | feat(voice): /voice command shim with sentinel flow |

### Commits
- `96713f2` refactor(voice): rewrite /voice shim with sentinel flow and dep checks
- `b9cf8df` test(voice): add e2e tests for /voice command

### Features
- `/voice` command with TTS/STT sentinel flow
- Dependency checking (graceful degradation if libs missing)

### Tests
~5 e2e tests

---

## MR4 — Video

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr4-video` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | feat(video): wire video pipeline into engine dispatcher |

### Commits
- `7a988dc` feat: wire video pipeline into engine dispatcher via oss_shims
- `44f793c` test: add e2e tests for video pipeline (10 tests, all mocked)

### Features
- Video generation pipeline (mocked for OSS)
- Engine dispatcher integration via oss_shims

### Tests
10 e2e tests (all mocked)

---

## MR5 — MCP (Model Context Protocol)

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr5-mcp` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | feat(mcp): full MCP server management with stdio transport |

### Commits
- `063036d` feat(mcp): fix imports, remove auto-init, add reset/reload helpers
- `d53b3ab` feat(mcp): rewrite /mcp command shim with full add/remove/list/reload
- `d1468e1` feat(mcp): hook initialize_mcp in engine startup registration
- `9fde7f2` test(mcp): add fake MCP stdio server and e2e tests

### Features
- `/mcp add|remove|list|reload` command
- Stdio transport with JSON-RPC
- Engine startup hook for MCP initialization
- Fake MCP server for testing

### Tests
~10 e2e tests

---

## MR6 — Plugin / Skill / Task / Memory

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr6-plugin-skill-task-memory` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | feat: plugin, skill, task & memory subsystems |

### Commits
- `bd7b123` refactor: unify tool registries — root shim re-exports backend
- `219eaf3` feat: wire memory tools into engine registration
- `1f79f7d` fix: update OSS shims for plugin and memory commands
- `803967e` test: add e2e tests for skill, task, memory, plugin features
- `7d7574c` docs: add extensibility policy section to MIGRATION.md

### Features
- Unified tool registry architecture
- Memory tools (persistent notes)
- Plugin loading system
- Skill/Task management
- Extensibility policy documented

### Tests
~15 e2e tests

---

## MR7 — Demos / HtmlRenderer / FolderDesc

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr7-demos-htmlrenderer-folderdesc` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | feat: html_renderer export and folder_desc tool |

### Commits
- `82321c5` docs: document /demo command impossibility in MIGRATION.md
- `be5bc18` test: add e2e test for html_renderer session JSON to HTML export
- `81281e7` test: add e2e test for folder_desc tool on tmp_path

### Features
- HTML renderer (session export to HTML)
- `folder_desc` tool (directory summarization)
- Documentation of `/demo` command status

### Tests
~5 e2e tests

---

## MR8 — Internal Test Suite

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr8-internal-test-suite` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | test: port complete internal test suite (1200+ tests) |

### Commits
- `0fd7720` test: port agent_loop tests from internal (98 pass, 6 skip, 1 xfail)
- `9e33208` test: port enforcement tests from internal (10 files, 51 pass)
- `e0c7365` test: port cache tests from internal
- `5d3d9fa` test: port checkpoint tests from internal
- `3304356` test: port dag tests from internal
- `99f0fed` test: port methodology and thinking tests from internal
- `230a489` test: port tools tests from internal (registry, runner, search, symbols)
- `08bcb51` test: port providers/agent tests from internal (bigctx_reminder, close_validator, task_classifier)
- `cd6f4ca` test: port plan_mode tests from internal
- `6447636` test: port sessions tests from internal
- `14177fe` test: port commands, compaction, profiles, prompts tests from internal
- `b607cac` test: port providers tests from internal (79 tests across root/auth/dispatch/wire)
- `a46629a` test: port regression tests from internal
- `87dabd5` test: port ui tests from internal (cli, display, paste_input)
- `97c552e` fix: handle missing bouzecode.web in is_web_ipc_active
- `ca51677` fix: guard is_web_ipc_active import for OSS (no bouzecode.web)

### Features
- Complete port of internal test suite covering all subsystems
- agent_loop, enforcement, cache, checkpoint, DAG, methodology, thinking
- tools (registry, runner, search, symbols), providers, sessions
- commands, compaction, profiles, prompts, plan_mode, regression, UI

### Tests
**1200+ tests** (98 agent_loop, 51 enforcement, cache, checkpoint, DAG, methodology, thinking, tools, providers, sessions, commands, compaction, profiles, prompts, plan_mode, regression, UI)

---

## MR9 — Telegram & Proactive

| Field | Value |
|-------|-------|
| **Branch** | `feat/mr9-telegram-proactive` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | feat(telegram): telegram command and proactive sentinel |

### Commits
- `b732b36` test: add e2e tests for telegram command and proactive sentinel

### Features
- `/telegram` command integration
- Proactive sentinel (scheduled notifications)

### Tests
~5 e2e tests

---

## MR10 — fix(parser) thinking backticks swallow tool_use

| Field | Value |
|-------|-------|
| **Branch** | `fix/parser-thinking-backticks` |
| **Base** | `feat/mr1-engine-core` |
| **Title** | fix(parser): thinking backticks no longer swallow tool_use |

### Context
Critical bug discovered DURING the migration: when an agent's thinking block contained triple-backticks, the streaming parser would incorrectly consider subsequent `tool_use` XML as still inside the thinking fence. This silently killed agent sessions — tool calls were never dispatched. The fix bufferizes the thinking block, handles streaming correctly, and escapes literal chevrons.

### Commits
- 2 commits (parser fix + regression tests)

### Features
- Streaming parser correctly closes thinking blocks even when they contain triple-backticks
- Literal chevrons (`<`/`>`) inside thinking are preserved without triggering XML parse
- Bufferized thinking accumulation prevents partial-match false positives

### Tests
23 regression tests

### Dependencies
MR1 (engine-core)

---

## Integration Branch

| Field | Value |
|-------|-------|
| **Branch** | `migration/integration` |
| **Base** | `main` |
| **Title** | docs: integration — MR10 final merge, migration complete (1425 tests green) |

### Description
Final integration branch that merges all MR1–MR10 branches in order. Serves as proof that all features coexist without conflicts and the full test suite passes.

- **1425 tests green** (0 failures, 2 env-skipped subprocess timeouts)
- All MR branches merged sequentially (MR1 → MR10 → MR2–MR9)
- Additional isolation fixes for CI environment
- MR10 (critical parser fix) integrated last — discovered and fixed during migration

---

## gh CLI Commands (ready to execute)

```bash
# MR1 — Engine Core
gh pr create --repo Simon-Free/bouzecode --base main --head feat/mr1-engine-core \
  --title "feat: port backend engine and UI from internal source" \
  --body "## Engine Core\n\nComplete backend engine (providers, agent loop, tools, sessions, DAG, methodology), UI layer, e2e test infrastructure, and MIGRATION.md.\n\n**Tests:** ~50 smoke + e2e\n**Dependencies:** None (base for all other MRs)"

# MR2 — Web V2
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr2-web-v2 \
  --title "feat(web_v2): port web frontend/backend with full test suite" \
  --body "## Web V2\n\nWeb server (FastAPI/Starlette), WebSocket IPC bridge, typologies, sessions, streaming endpoints.\n\n**Tests:** ~120 tests\n**Dependencies:** MR1"

# MR3 — Voice
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr3-voice \
  --title "feat(voice): /voice command shim with sentinel flow" \
  --body "## Voice\n\n/voice command with TTS/STT sentinel flow and dependency checking.\n\n**Tests:** ~5 e2e\n**Dependencies:** MR1"

# MR4 — Video
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr4-video \
  --title "feat(video): wire video pipeline into engine dispatcher" \
  --body "## Video\n\nVideo generation pipeline (mocked for OSS), engine dispatcher integration via oss_shims.\n\n**Tests:** 10 e2e (mocked)\n**Dependencies:** MR1"

# MR5 — MCP
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr5-mcp \
  --title "feat(mcp): full MCP server management with stdio transport" \
  --body "## MCP\n\n/mcp add|remove|list|reload command, stdio transport with JSON-RPC, engine startup hook.\n\n**Tests:** ~10 e2e\n**Dependencies:** MR1"

# MR6 — Plugin/Skill/Task/Memory
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr6-plugin-skill-task-memory \
  --title "feat: plugin, skill, task & memory subsystems" \
  --body "## Plugin / Skill / Task / Memory\n\nUnified tool registry, memory tools, plugin loading, skill/task management, extensibility policy.\n\n**Tests:** ~15 e2e\n**Dependencies:** MR1"

# MR7 — Demos/HtmlRenderer/FolderDesc
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr7-demos-htmlrenderer-folderdesc \
  --title "feat: html_renderer export and folder_desc tool" \
  --body "## Demos / HtmlRenderer / FolderDesc\n\nHTML renderer (session export), folder_desc tool, /demo documentation.\n\n**Tests:** ~5 e2e\n**Dependencies:** MR1"

# MR8 — Internal Test Suite
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr8-internal-test-suite \
  --title "test: port complete internal test suite (1200+ tests)" \
  --body "## Internal Test Suite\n\nComplete port of internal tests: agent_loop, enforcement, cache, checkpoint, DAG, methodology, thinking, tools, providers, sessions, commands, compaction, profiles, prompts, plan_mode, regression, UI.\n\n**Tests:** 1200+\n**Dependencies:** MR1"

# MR9 — Telegram & Proactive
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head feat/mr9-telegram-proactive \
  --title "feat(telegram): telegram command and proactive sentinel" \
  --body "## Telegram & Proactive\n\n/telegram command integration, proactive sentinel (scheduled notifications).\n\n**Tests:** ~5 e2e\n**Dependencies:** MR1"

# MR10 — fix(parser) thinking backticks
gh pr create --repo Simon-Free/bouzecode --base feat/mr1-engine-core --head fix/parser-thinking-backticks \
  --title "fix(parser): thinking backticks no longer swallow tool_use" \
  --body "## fix(parser) thinking backticks swallow tool_use\n\nCritical bug discovered during migration: triple-backticks in thinking blocks caused the streaming parser to swallow subsequent tool_use XML. Sessions died silently.\n\n**Fix:** bufferized thinking accumulation, streaming-safe fence detection, literal chevron preservation.\n\n**Tests:** 23 regression tests\n**Dependencies:** MR1"

# Integration
gh pr create --repo Simon-Free/bouzecode --base main --head migration/integration \
  --title "docs: integration — complete migration (1425 tests green)" \
  --body "## Integration\n\nFinal merge of all MR1-MR10 branches. Proof that all features coexist without conflicts.\n\n**1425 tests green** (0 failures)\n\nMerge order: MR1 first, then MR10 (critical parser fix), then MR2-MR9 in any order, or merge this branch directly for the complete migration."
```
