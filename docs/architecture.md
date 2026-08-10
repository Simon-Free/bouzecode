# Architecture

How bouzecode is put together, and why. Read the root [`README.md`](../README.md) first for what the tool does; this document is about the shape of the code.

---

## The two front ends, one engine

```
  ui/  (terminal)          web_v2/  (Flask)
        \                    /
         \                  /
          →   backend/   ←
              the engine
```

`src/bouzecode/backend/` is the whole engine: the turn loop, the tool registry, the providers, the context discipline. It knows nothing about a terminal or a browser.

`src/bouzecode/ui/` is the terminal front end — argument parsing, the REPL, ANSI rendering, replay.

`src/bouzecode/web_v2/` is the web front end. It does not wrap the terminal: it **spawns agent processes** and reads their structured output. The rule that shapes the whole package is that **stdout is never parsed**. Every view is rendered server-side from the session JSON, the agent IPC files and the payload dumps.

Both entry points are declared in `pyproject.toml`: `bouzecode` → `bouzecode:main`, `bouzegui` → `bouzecode.web_v2.app:main`.

---

## The turn loop

```
user prompt
    │
    ▼
build the system prompt          backend/core/context.py + src/system_prompts/
    │
    ▼
send to the provider             backend/agent/providers/
    │
    ▼
parse the model's tool calls     backend/xml_tool_protocol/  (or native function calling)
    │
    ▼
build the dependency graph       backend/agent/dag.py
    │
    ▼
execute level by level,
in parallel within a level       backend/core/tool_registry.py → backend/tools/ops/
    │
    ▼
inject the results back          backend/agent/loop_turn.py
    │
    └────────────► next turn, or close
```

Three details carry most of the design:

**The DAG.** A turn is not one tool call, it is a *batch*. The model declares `depends_on` between the calls it emits; `dag.py` turns that into a graph and runs each level in parallel. Everything that could have fit in one turn does fit in one turn — which is the whole point of the project, because the bill is the number of round-trips.

**Two tool-call protocols.** OpenAI-compatible endpoints use native function calling. Anthropic endpoints use a text protocol implemented in `backend/xml_tool_protocol/` — a parser, a serializer, and a docs generator that teaches the model the syntax. The protocol is chosen per endpoint and can be forced either way (`BOUZECODE_ANTHROPIC_NATIVE_TOOLS`). `recovery.py` handles the malformed emissions that a text protocol inevitably produces.

**Closing is validated.** A turn does not end because the model stopped talking. `backend/agent/close_validator.py` and `close_guard.py` check that the agent produced what its profile owes — a `FinalAnswer`, a recap when required, a methodology entry — and re-open the turn otherwise.

---

## The tool registry

`backend/core/tool_registry.py` is the single source of truth. A tool is a `ToolDef`: a name, a JSON schema, a callable `(params, config) -> str`, and two flags — `read_only` (drives the permission gate) and `concurrent_safe` (drives the DAG's parallelism).

Registration all happens in `backend/tools/registration.py`, and the *order* is load-bearing:

1. The core built-ins are bound from `backend/tools/schemas.py` to their implementations in `backend/tools/ops/`.
2. Plan-mode and project tools are added.
3. Side-effect imports pull in the tools owned by other packages: `backend/multi_agent/`, `backend/tools/skill/`, `backend/tools/task/`, `backend/tools/folder_desc/`, `backend/tools/agents_map/`, `backend/tools/projects_tool/`, and the flat top-level `memory/`.
4. Plugin tools are registered, unless `BOUZECODE_NO_PLUGINS` is set.
5. **A whitelist pass disables everything outside the default set.** What survives is `FRAMEWORK_ALWAYS_ON` — the twelve discipline tools a profile can never strip — plus a small work set (`Read`, `Write`, `Edit`, `Bash`, `BashOutput`, `Glob`, `Grep`, `RunPythonTest`, `WebFetch`, `WebSearch`, `AddProject`, `MemorySave`, `MemoryList`).
6. chrome-devtools and MCP register *after* that pass, on purpose, so their `enable_tool()` calls are not undone.

The reason for a whitelist at all: every enabled tool ships its JSON schema on every single turn. Forty schemas is a permanent tax on the input bill. Enabling a tool by default is a budget decision.

An agent profile then narrows or widens the set for its own session, through a thread-local overlay so parallel conversations do not fight over the global registry.

---

## Context discipline

This is where the token savings actually come from. Three mechanisms, all in `backend/context_manager/` and `backend/agent/`:

- **`Methodology`** — an append-only named scratchpad the model maintains. It survives compaction; the raw turns do not.
- **`Snippet`** — the model freezes the line ranges of a tool result that matter and the rest is dropped from the context. A 1 200-line read becomes the forty lines it needed.
- **`trash`** — the model marks stale tool results for removal outright.

None of it is optional. `backend/agent/enforcement_call.py` fires a side-call when a read went un-snippeted or a methodology entry is missing, and recovers the bookkeeping *before* the next turn rather than letting it drift. `BOUZECODE_NO_ENFORCE=1` turns that off for tests.

Above them sit the compaction layers: cheap snipping of old tool results, then a model-summarised compaction when that is not enough. `compact_judge.py` decides whether a deep compaction is worth its own LLM call.

Navigation is pre-indexed rather than explored: `GetFolderDescription` returns an annotated file tree in a few hundred tokens, `AgentsMap` and `SymbolMap` return a per-folder map of the repository and its symbols. All three replace the "spawn an explorer sub-agent" pattern that typically burns tens of thousands of tokens.

---

## Providers

`backend/agent/providers/registry.py` is a pure function from a model string to `(provider, api_model_id)`. `--model sonnet`, `--model deepseek-v4-flash` and `--model anthropic/claude-opus-4-8` all resolve without configuration.

Three provider slots:

| Slot | Transport | Endpoint |
|---|---|---|
| `anthropic` | Anthropic SDK, native or XML tools | official API, or anything Anthropic-compatible via `ANTHROPIC_BASE_URL` |
| `openrouter` | OpenAI-compatible | `https://openrouter.ai/api/v1` |
| `gateway` | OpenAI-compatible | entirely from the environment — `BOUZECODE_GATEWAY_BASE_URL` / `_API_KEY` / `_MODELS` |

**No base URL is ever hardcoded.** The `gateway` slot exists so you can point bouzecode at your own LiteLLM, vLLM or in-house proxy; with its variables unset it simply stays inert and resolves nothing.

The same file carries the per-model input/output rates and the cache-read overrides for providers that do not follow the 0.1×-input convention. Those numbers feed the cost columns in the web UI, which is the only reason cost reporting is trustworthy.

`providers/backends/` holds the actual clients: the Anthropic streaming and native paths, the OpenRouter streaming and native paths, and `dispatch.py` choosing between them.

---

## Agents and isolation

A sub-agent is a real process, not a nested function call. `backend/multi_agent/` owns the spawning, the depth limit (`max_agent_depth`), the concurrency limit (`max_concurrent_agents`) and the message queues.

An **agent profile** (`backend/profiles/`) declares what an agent is: a tool whitelist, skills, hooks, an optional model override and a system-prompt supplement. Resolution goes builtin < `~/.bouzecode/profiles/` < `<cwd>/.bouzecode/profiles/` < `--extra-dir`, so a project can shadow a built-in agent under the same name. The built-ins live in `backend/profiles/builtin/`: `manager`, `general-purpose`, `coder`, `frontend`, `meta-agent`, plus the `deferred` fragment that is composed into every top-level agent.

Whether an agent may **write** is derived from the tools its profile actually grants, never from the name of its typology. That derivation is what makes the collision guard correct: two writing agents in the same tree would overwrite each other, so the second is moved to a worktree — while a read-only `manager` is not counted, because it overwrites nobody.

Isolation has exactly three values (`web_v2/services/work/isolation.py`): `shared`, `worktree`, `worktree+venv`. Not two booleans — "no worktree but a dedicated venv" is meaningless and is deliberately not representable. A `worktree` agent borrows the base repository's venv through `VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT` and a `PATH` prefix, so parallel agents do not each grow a gigabyte-sized environment.

---

## The web UI

```
web_v2/
├── app.py        # app factory; /api/schema derived from app.url_map
├── routes/       # HTTP only — parse, validate, delegate, jsonify
├── services/     # the logic, Flask-free and independently testable
├── runtime/      # agent lifecycle: runner, IPC, warm pool, venv env, context viewer
├── templates/    # conversations, session, agent-builder, base
└── static/       # dark-theme CSS, ES modules, vendored Monaco (no CDN)
```

Three invariants:

**Routes are thin.** `routes/` does HTTP; `services/` does the thinking. Because the services never import Flask, most of the suite tests them directly, and the Flask test client only has to cover the HTTP contract.

**The API schema is derived, never written.** `GET /api/schema` is built from `app.url_map`, so it cannot describe a route that no longer exists nor miss one that was added.

**No CDN.** Monaco is vendored under `static/vendor/monaco`, with a `difflib` fallback when the vendor copy is absent. A developer tool that needs the public internet to render a diff is a developer tool that stops working at the wrong moment.

State lives on disk under `~/.bouzecode/web_v2/` (projects, tickets) and `~/.bouzecode/sessions/` (session logs). Nothing is deleted: archiving removes an item from the board and keeps it in its store.

---

## The flat top-level packages

Beside `src/`, the repository keeps a set of packages at the root: `memory/`, `mcp/`, `voice/`, `video/`, `plugin/`, `html_renderer/`, and flat counterparts of the engine packages (`commands/`, `tools/`, `providers/`, `ui/`, `skill/`, `task/`, `checkpoint/`, `multi_agent/`, `folder_desc/`, `xml_tool_protocol/`), plus a handful of top-level modules (`config.py`, `compaction.py`, `context_gc.py`, `tool_registry.py`, `cloudsave.py`).

They are live code, reached two ways:

- `backend/tools/registration.py` imports `memory.tools` and `mcp.tools` for their tools;
- `backend/commands/oss_shims/` wraps six of them into slash commands — `/memory`, `/mcp`, `/plugin`, `/voice`, `/video`, `/video-wizard` — and merges the result into the dispatcher's `COMMANDS` table.

`pyproject.toml` ships them by scanning both `src` and `.` as package roots, with an explicit `exclude` so the src-layout is not re-discovered a second time under a bogus name.

---

## Where state lives

| Path | Contents |
|---|---|
| `~/.bouzecode/config.json` | persistent settings |
| `~/.bouzecode/sessions/` | session logs — `daily/YYYY-MM-DD/`, plus `history.json` |
| `~/.bouzecode/skills/`, `profiles/` | your global skills and agent profiles |
| `~/.bouzecode/agent_catalog/` | the pulled shared-agent catalogue |
| `~/.bouzecode/mcp.json` | user-level MCP servers |
| `~/.bouzecode/worktrees/` | agent worktrees |
| `~/.bouzecode/web_v2/` | projects and tickets served by the web UI |
| `<project>/.bouzecode/` | per-project `skills/`, `plugins/`, `profiles/` |
| `<project>/.mcp.json` | per-project MCP servers |

Nothing under `~/.bouzecode/` is required to exist: every path is created on demand, and a fresh machine boots with the built-in defaults.

---

## Documentation as a build artifact

Every code folder carries a `README.md` stating its purpose, its subfolders and its symbols. They are the navigation surface the agent itself uses — finding a function is a lookup, not a grep sweep.

`readme_sync/` keeps them honest: `python -m readme_sync --check` reports any map that has drifted from the code it describes, `--list-stale` names them, `--regen` rebuilds one. The contract those files must satisfy is declared in `readme_sync/contract.py`.

---

## Design rules, in one list

- **The bill is the number of round-trips.** Every design decision that looks strange is usually the cheapest way to remove one.
- **Every enabled tool costs tokens on every turn.** Default-on is a budget decision.
- **The registry is the single source of truth.** If the model can call it, it is a `ToolDef` — not a branch in the loop.
- **Discipline is enforced, not requested.** A prompt that asks the model to snippet its reads, without a mechanism that checks, is a prompt that will be ignored on turn nine.
- **Never hardcode an endpoint.** Base URLs, hosts and credentials come from the environment.
- **Never parse stdout.** Structured output or nothing.
- **Derive, don't duplicate.** The API schema comes from the URL map, the folder maps come from the code, the write-capability of an agent comes from its tool list.
