# tests/backend/

## Purpose
The hub of the backend test tree: everything that exercises `bouzecode.backend`
(agent loop, providers, tools, prompts, sessions, profiles) lives in the subfolders
below. The `.py` files at this level are the cross-cutting checks that belong to no
single theme. `TEST_METHODOLOGY.md` and `TEST_TRIAGE.md` sit here as prose companions.

## Usage
- `test_no_leaked_tool_markup.py` — walks every `.py` under `src/bouzecode` and `tests/` and fails if a leading `# [desc] … [/desc]` header comment contains emitted tool markup (`<tool_use name=`, `</tool_use>`, `<param name=`).
- `test_payload_view.py` — the per-turn payload journal: `fold_records`, `load_turn_records`, `load_turn_map` rebuild whole payloads from deltas (append, compaction, absolute record), and `payload_dump.dump_turn_payload` writes large notes and system blocks once.
- `test_profile_flag.py` — `get_agent_profile_extra`: a named profile resolves from `.bouzecode/profiles`, an unknown name yields only the built-in capabilities, `autre` and `""` map to the default profile.
- `test_recovery_no_tools.py` — `handle_no_tools` on a thinking-only turn: side-call recovery then continuation, a cap of three consecutive recoveries falling back to bounce-and-close, plain bounce when `recover_memory` is off, and counter reset.
- `test_shims_smoke.py` — the six shim commands (`/voice`, `/mcp`, `/plugin`, `/memory`, `/video`, `/video-wizard`) are registered, documented in `/help`, run through `handle_slash` and print their result; the memory/plugin/MCP stores are repointed at `tmp_path`.
- `test_thinking_log_per_turn.py` — `flush_thinking` writes one entry per turn, skips empty turns, and empties the accumulator.
- `test_tool_examples_injection.py` — `build_system_prompt_parts` injects XML tool examples for Anthropic models and JSON `tool_calls` examples for OpenRouter models, with the `{tool_examples}` placeholder always replaced.
- `test_video_e2e.py` — `/video` and `/video-wizard`: status output, dependency reporting, pipeline invocation, registration and shim signature, with the external binaries stubbed.

## Subfolders
| Folder | Description |
|--------|-------------|
| `agent/` | Agent-level behaviour around the loop: close validation, hook pipeline, task classifier, API-error close reason, resume of a paused input. |
| `agent_loop/` | The turn loop: closing rules (FinalAnswer, recap, meta-only), loop detectors, partial-stream recovery, enforcement persistence, artifacts wiring. |
| `agents_map/` | The generated symbol/agents map: drift contract against the live AST, regeneration guards and progress, read fallbacks. |
| `cache/` | Anthropic prompt-cache stability: frozen prefix across turns, breakpoint pinning, token accounting. |
| `checkpoint/` | Snapshots and rollback: store backups, `GetDiff`, and the `/revert` bookkeeping. |
| `chrome_devtools/` | The chrome-devtools launcher, driven against a real minimal stdio MCP server (`fake_mcp_server.py`). |
| `commands/` | Slash commands: `/agent` switch, `/agent-upgrade`, `/resume` picker, wire export, profile skill wiring, and `info/` for `/doctor`. |
| `compaction/` | Context compaction: token estimation, snip and split points, the judged deep pass over notes, embedded prompt data. |
| `config/` | Configuration defaults read from `load_config`. |
| `conformity/` | Guards against one failure class: the harness presenting as live what is dead (documented mechanisms reachable, declared skills loadable). |
| `core/` | Core helpers: GitLab source resolution, and the worktree contract injected into the system prompt. |
| `dag/` | The tool-batch DAG: `depends_on` resolution and its accepted syntaxes, concurrency, denial cascade, interruption mid-batch. |
| `enforcement/` | Methodology/Snippet enforcement: forced recovery before execution, cache stability, thresholds, best-effort failure. |
| `methodology/` | The Methodology note and the Snippet tool: append-only semantics, timeline deltas, wire transmission, cache split, turn-ending rules. |
| `multi_agent/` | The Agent and Task tools: sub-agent spawn/wait/cancel, web dispatch, manager type guard, terminal sub-agents. |
| `plan_mode/` | Plan mode: the WritePlan contract, auto-validator verdicts, tool gating, and the IPC of a parked validation. |
| `plugin/` | Plugin store, resolver, and hook registration. |
| `profiles/` | Agent profiles: loading, composition, built-in capabilities, per-profile hooks and loop flags, remote catalog. |
| `prompts/` | System prompt assembly: template rendering, prompt file loading, memory context, and the rule that injected text never names an uncallable tool. |
| `providers/` | Provider transport: Anthropic native tools over SSE, OpenRouter conversion and retries, dispatch routing, auth errors, wire payload shape. |
| `readme_sync/` | Folder-map naming settings of the `readme_sync` package. |
| `regression/` | Repo-wide guards: removed features stay removed, imports and version resolve, packaging and launchers keep their shape. |
| `sessions/` | Session records: live saves, close reason, final-answer persistence, save/restore, and resume of an interrupted agent. |
| `skills/` | Skill definitions: frontmatter parsing, scope resolution, shadow reporting, grep, and the guidance that reaches the model. |
| `startup/` | Startup wiring: project `.bouzecode/` auto-detection, the extra-directory registry, `LoadProjectConfig`, package import smoke. |
| `thinking/` | The thinking channel: stream parser edge cases, archiving thinking into assistant content, and the overflow budget. |
| `tools/` | The tool registry and the tools themselves: enable/disable, output truncation, Edit/Read/Glob/Grep/Bash behaviour, test runner, symbols. |
| `web_v2/` | Web-server services exercised without network. |
| `xml_protocol/` | The XML tool protocol: incremental stream parser, CDATA, backticks, `depends_on` quoting, serializer, generated docs. |
| `xml_tool_protocol/` | Backticks inside `<thinking>` must not swallow a real `<tool_use>` tag. |
