# Bouzécode

> A fork of [**CheetahCode**](https://github.com/SafeRL-Lab/clawspring) (Nano Claude Code) by BouzéLab, itself inspired by Claude Code.

English · [Français](./docs/README.FR.MD)

**This project is a PoC.** What matters here are the **ideas** for shrinking the token cost of a code agent *at equal model capability* — not the implementation quality, which is honestly rough, because we didn't really have the time to polish it. If an idea speaks to you, feel free to re-implement it cleanly in your own stack.

The angle is strict: **reduce the number of tokens consumed without degrading the reasoning capability** of the underlying model. We therefore deliberately avoid downgrades to smaller models, and only work on the *shape* of the context sent to the top-tier model.

Bouzécode is a fast, hackable Python AI coding assistant with two faces on the same engine: a terminal agent (REPL), and a web UI that drives a fleet of agents in parallel.

**Language note.** The engine, the tools and this documentation are in English, and so are both front ends by default. The web UI is bilingual: a language selector sits in the top bar next to the *Conversations* / *Agents* / *API* links, it switches every label between English and French without reloading, and the choice is remembered by the browser. The terminal prints English unless `BOUZECODE_LANG` starts with `fr`.

---

## 🎯 Interactive presentation

**[▶ View the interactive presentation — token savings explained](https://simon-free.github.io/bouzecode/)**

A visual walkthrough of how Bouzécode achieves ~10× token reduction in agentic coding workflows.

---

## Install

### Prerequisites

- **Python** ≥ 3.11 (3.13 is what the launchers pin when they create the venv).
- **[uv](https://astral.sh/uv)** — used for venv + dependency resolution. Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
- **ripgrep (`rg`)** — strongly recommended: the `Grep` tool shells out to it. `bouzecode.ps1` installs it through `winget` if it is missing, and the CLI itself downloads a copy into `~/.local/bin` on Windows when `rg` is absent from `PATH`. Elsewhere: `brew install ripgrep` or `apt install ripgrep`.
- An **API key** for whichever provider serves your model. The default model is an Anthropic one, so `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) is the usual answer; OpenRouter and an OpenAI-compatible gateway of your own are the two other slots — see [Pick a provider](#pick-a-provider).

### Windows (one-shot launchers)

```powershell
git clone https://github.com/Simon-Free/bouzecode.git
cd bouzecode
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # or put it in a .env file at the repo root

.\bouzecode.ps1              # terminal agent (REPL)
.\bouzegui.ps1               # web UI on http://127.0.0.1:5055
.\bouzegui.ps1 5099          # web UI on another port
```

Both launchers are self-contained: they load `.env`, locate `uv`, create the venv, install the project in editable mode, and start. `bouzecode.ps1` uses `.venv/` and also checks `ripgrep`; `bouzegui.ps1` uses a separate `.venv-ui/` with the `[web]` extra. Each of them re-syncs dependencies only when `pyproject.toml` is newer than its install stamp.

The order of those steps is a feature: `.env` is read **before** anything is installed, so on a network where the package index is only reachable through a proxy, putting `BOUZECODE_PROXY_URL` / `_USER` / `_PASSWORD` — or your index credentials — in that file is enough to bootstrap from a bare clone.

Three more scripts sit at the root: `bouzecode_publish.ps1` (build and publish the package), `bouzecode_self_update.ps1` (update the working copy in place) and `bouzecode_self_update_detached.ps1` (the variant that survives the process it updates). `load_dotenv.ps1` is the shared `.env` reader all of them dot-source.

### macOS / Linux

There is no shell launcher — install once with `uv` and call the entry points:

```bash
git clone https://github.com/Simon-Free/bouzecode.git
cd bouzecode
uv venv --python 3.13
uv pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...

.venv/bin/bouzecode                          # REPL
.venv/bin/bouzegui                           # web UI, http://127.0.0.1:5056
.venv/bin/python -m bouzecode.web_v2         # same thing, as a module
```

`.env` at the repo root is loaded by the PowerShell launchers and by the test suite; if you call the entry points directly, `source` it or export the variables yourself.

### What gets installed

`pyproject.toml` declares two console scripts — `bouzecode` (the REPL) and `bouzegui` (the web UI) — and pulls in anthropic, openai, httpx, requests, rich, markdown, flask, psutil, pyyaml, prompt-toolkit, tqdm and tree-sitter (with the JavaScript and TypeScript grammars). That is the whole install: no compiled step, no external service to wire up beyond the API key.

Optional extras, each installable with `uv pip install -e ".[<extra>]"`:

| Extra | Pulls in | For |
|---|---|---|
| `web` | flask, psutil, pyyaml | the web UI |
| `test` | pytest, pytest-xdist, pytest-playwright, pytest-timeout | the test suite |
| `voice` | sounddevice | `/voice` dictation |
| `vision` | Pillow | image handling |

The Telegram bridge has no extra of its own: it talks to the Bot API over the standard library and imports no third-party client.

### Pick a provider

The model decides the provider, and the provider decides which variable must carry a key. The default model is Anthropic's, so a bare install expects `ANTHROPIC_API_KEY`. With a key for something else, name a model that something else serves — that is the whole of it. Three slots:

| You have | Set | Then run with |
|---|---|---|
| an Anthropic key | `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) | nothing to change — `opus`, `sonnet`, `haiku`, any `claude-*` |
| an OpenRouter key | `OPENROUTER_KEY` (or `OPENROUTER_API_KEY`) | `--model deepseek-v4-flash` (also `deepseek-v4-pro`, `kimi-k2.7-code`, `kimi-k3`, `glm-5.2`) |
| an OpenAI-compatible endpoint | `BOUZECODE_GATEWAY_API_KEY`, plus `BOUZECODE_GATEWAY_BASE_URL` and `BOUZECODE_GATEWAY_MODELS` | `--model <one of the names you listed>` |

```bash
export OPENROUTER_KEY=sk-or-...
.venv/bin/bouzecode --model deepseek-v4-flash        # this run only
```

```bash
export BOUZECODE_GATEWAY_BASE_URL=https://gateway.example.com/v1
export BOUZECODE_GATEWAY_API_KEY=...
export BOUZECODE_GATEWAY_MODELS=gpt-5,gemini-3-pro
.venv/bin/bouzecode --model gpt-5
```

To make the choice stick, set it once from inside the REPL — `/model deepseek-v4-flash` writes it to `~/.bouzecode/config.json`, as does `/config model=deepseek-v4-flash` — and every later session starts on it.

If the chosen model's provider has no key, the run stops before the first call: it prints which providers *do* hold a key here, a ready-to-paste `--model` for each of them, and the variable to set for the one you asked for. That is a configuration error, so it exits with code 2 and no traceback.

### Verify

```powershell
.venv\Scripts\bouzecode.exe --version
```
```bash
.venv/bin/bouzecode --version
```

Then, inside the REPL, `/doctor` — it diagnoses the installation (interpreter, git, key and provider reachability, `rg`, tool registry, optional modules) and names whatever is missing, closing on a `N passed, N warnings, N failures` line.

---

## The terminal agent

`bouzecode` opens a REPL. You type an intent in plain language; the agent reads the code, freezes a plan, then edits and tests. The display streams the model's reasoning, each tool call as it starts and ends, and a colored diff after every `Write`/`Edit`.

```
$ .venv/bin/bouzecode
> add a --dry-run flag to the export command, with a test

  ⏺ Read  src/exporter/cli.py
  ⏺ Grep  "def export"  (content)
  ⏺ WritePlan
  ⏺ Edit  src/exporter/cli.py       +12 -3
  ⏺ Write tests/test_export_dry_run.py
  ⏺ RunPythonTest  tests/test_export_dry_run.py     3 passed
```

Useful flags:

| Flag | Effect |
|---|---|
| `-p`, `--print` | Non-interactive: run the prompt and exit |
| `-m`, `--model MODEL` | Override the model for this run |
| `--cwd PATH` | Working directory (default: launch directory) |
| `--profile NAME` | Apply an agent profile to the top-level agent |
| `--accept-all` | Never ask permission |
| `--verbose` | Show thinking and token counts |
| `--thinking` | Enable extended thinking |
| `--loud` | Think-out-loud mode (visible `<thinking>` tags) |
| `--extra-dir PATH` | Extra `.bouzecode`-structured directory for skills/plugins/profiles (repeatable) |
| `--enable-chrome-devtools` | Attach the chrome-devtools browser tools (off by default: ~5k tokens of schemas) |
| `--session-file` / `--resume-from` | Persist and restore session state |
| `--plan-output PATH` | Write the final response to a markdown file |
| `--version [TAG]` | Print the version; with a tag, switch the working copy to it |

`-p` is meant for a pipe and for CI: it takes the prompt as positional arguments, prints the run and exits. The loading animation only paints on a real terminal, so redirected output carries the answer and nothing else. A configuration error — a model whose provider holds no key — exits with code 2 and one short paragraph, not a traceback, which is what makes it usable as a build step.

```bash
.venv/bin/bouzecode -p "summarise what src/bouzecode/ui/ does" > answer.md
```

### Built-in commands

| Command | Effect |
|---|---|
| `/help` `/clear` `/exit` (`/quit`) | List commands, clear the history, quit |
| `/model [m]` `/config [k=v]` `/cwd [path]` | Show or set the model, a config key, the working directory |
| `/permissions [mode]` | `auto`, `accept-all` or `manual` |
| `/thinking` `/verbose` | Cycle thinking (off / extended / loud); toggle verbose output |
| `/context` `/cost` `/timing` | Context fill, cost estimate, time spent per tool and per LLM call |
| `/history` `/diff` `/compact` | Conversation history, diffs from recent `Edit`/`Write`, history compaction |
| `/checkpoint` `/rewind` `/revert` | List and restore file checkpoints; undo back to the last user input |
| `/save` `/load` `/resume` `/where` | Session persistence and the interactive session picker |
| `/plan` | Enter or leave plan mode |
| `/agent [name]` `/agents` `/agent-upgrade` | Switch the session to a profile; show background agents; install the plugins a profile requires |
| `/skills` `/tasks` (`/task`) `/tools` | List skills, manage tasks, list/enable/disable tools |
| `/export` `/copy` `/init` | Export the conversation, copy the last answer, write a `CLAUDE.md` template |
| `/memory` `/mcp` `/plugin` | Stored memories, MCP servers, plugin packages (see [Subsystems](#subsystems)) |
| `/voice` `/video` `/video-wizard` | Dictation, and the scripted-video pipeline |
| `/doctor` | Diagnose installation health |

Typing `/<skill-name>` runs a skill directly; an unknown slash command is matched against the skill triggers before failing.

---

## Subsystems

Beside the engine under `src/bouzecode/`, the repository keeps a set of flat top-level packages. They are live code: `src/bouzecode/backend/commands/oss_shims/` wires their slash commands into the dispatcher, and `backend/tools/registration.py` imports two of them for their tools.

| Package | What it gives you | Reached through |
|---|---|---|
| `memory/` | Durable user- and project-scoped memories, searched and injected into the system prompt | `/memory`, and the `MemorySave` / `MemoryList` / `MemorySearch` / `MemoryDelete` tools |
| `mcp/` | MCP servers over stdio or HTTP; their tools join the registry at startup | `/mcp`, configured in `~/.bouzecode/mcp.json` (user) and `.mcp.json` (project, looked up from `cwd` upwards) |
| `plugin/` | pip-installable tool packages, enabled per user or per project | `/plugin`, and the agent-builder page |
| `voice/` | Push-to-talk capture (sounddevice, `arecord` or `sox`) transcribed into the prompt | `/voice` — needs the `[voice]` extra |
| `video/` | Scripted-video pipeline: story → TTS → images → subtitles → assembly | `/video`, `/video-wizard` |
| `html_renderer/` | Turns a session's structured JSON into standalone HTML blocks | used by the replay and export paths |
| `commands/` `tools/` `providers/` `ui/` `skill/` `task/` `checkpoint/` `multi_agent/` `folder_desc/` `xml_tool_protocol/` | Flat counterparts of the engine packages, kept importable so a plugin or a script can reach them without going through `bouzecode.backend` | direct import |

`config.py`, `compaction.py`, `context_gc.py`, `tool_registry.py` and `cloudsave.py` are shipped as top-level modules for the same reason.

---

## The web UI

```powershell
.\bouzegui.ps1                          # Windows — http://127.0.0.1:5055
```
```bash
.venv/bin/bouzegui --port 5056          # anywhere — default port 5056
python -m bouzecode.web_v2 --port 5056  # same, as a module
```

The server binds `127.0.0.1` and refuses to boot if the port is already served. The premise: **stdout is never parsed** — every view is rendered server-side from the structured session JSON, the agent IPC files and the payload dumps.

Every page runs offline. No font, stylesheet or script is fetched from a third-party host: the CSS is local, the Monaco editor is vendored in the tree, and the typography is whatever your system provides. A developer tool that needs the public internet to render a diff is a developer tool that stops working at the wrong moment.

The interface speaks English and French. The selector sits in the top bar, after the *Conversations* / *Agents* / *API* links; switching repaints the labels in place, with no reload and no loss of what is on screen, and the browser remembers the choice for the next visit. The labels quoted below are the English ones.

### The inbox

`/` redirects to `/conversations`, the home page. On the left, the **Conversations** sidebar lists everything that runs or has run, in three sections — **⚠ Needs attention**, **● Running**, **Done** — so the first thing you see on arrival is what needs you. Sub-agents are nested under the agent that dispatched them, and a search box above the list runs a full-text query over **Open** or **All** conversations.

At the top of the right pane sits the launch bar: a text area — *"New conversation — describe what needs doing (Enter to send)…"* — and a **Send** arrow. Type a prompt, hit send, and an agent starts. The ticket title is the first line of the prompt.

### The Options panel

Folded under the prompt area, **Options** carries the three launch settings:

- **Project** — the repository the agent will work in. Nothing is guessed: until you pick one the value reads *pick one*, and a dispatch without a project comes back as **Project required** with the registered projects offered as buttons. The same panel opens a project of its own, from a *name*, an *absolute path* and an optional *description*; the **Add** button posts it, and a refusal from the server (folder not found, project already open) is shown as-is under the fields.
- **Agent type** — the agent typology (see below).
- **Environment** — the isolation mode: `shared`, `worktree` or `worktree+venv` (see [Execution modes](#execution-modes)), each with a one-line description of what it provisions and when to pick it.

### Typologies

`default` is the standard agent: no profile, the full default toolset. It reads, writes the code and runs the tests itself. Pick it for **short, self-contained tasks** — one agent, one working tree, one answer.

The built-in profiles live in `src/bouzecode/backend/profiles/builtin/`:

- **`manager`** — a **read-only dispatcher**. It holds `Read`, `Glob`, `Grep`, `Agent`, `MessageAgent`, `ListAgentTypes` and `Fleet` — no `Write`, no `Edit`, no `Bash`. It never codes, never tests and never validates the work itself. For each batch it makes exactly three decisions: **which typology** should handle it (chosen through `ListAgentTypes`), **in what order** the agents run (serial when one result feeds the next, parallel when the batches are independent), and it **aggregates the verdicts** its children come back with. Pick it for **work that splits** into several independent or chained batches.
- **`general-purpose`** — the light, fast generalist, with the `commit` and `review` skills.
- **`coder`** — Python work in an isolated worktree, under a recap contract.
- **`frontend`** — drives a browser through the chrome-devtools tools to re-read its own rendering: render → screenshot → self-critique → fix.
- **`meta-agent`** — building new agents, profiles, tools and skills; it delegates heavy code edits rather than doing them.

A sixth file, `deferred.yaml`, is a *fragment*: not a typology you can pick, but a prompt supplement composed into every top-level agent, carrying the deferred-Bash rule.

Because a manager cannot write, it is excluded from the shared-tree collision guard — a read-only agent overwrites nobody, so it never forces a worktree on a neighbour.

### Following a conversation

Click a conversation to open it as a tab in the right pane. Each tab carries a **Conversation / Recap** switch — the recap side lights up once the session ends, until then it reads *available once the session ends* — plus a composer at the bottom (*"Message / follow-up… (Enter to send, Ctrl+C to interrupt)"*) to answer a question or relaunch the agent, and a **Relaunch** control in the header. An agent that died without a proven closure is flagged **crashed** and offers **Resume**; **Kill agent** stops a live one.

`/sessions` lists every session ever recorded, and `/sessions/<key>` opens one in full, with four tabs:

- **Conversation** — the feed of turns: the model's reasoning, then each tool call as an expandable block. Text streams in while the agent is still producing it;
- **Changed files** — the diffs the run produced, rendered server-side, with a vendored Monaco editor for side-by-side reading (a `difflib` fallback covers the case where the vendor copy is absent);
- **Turns (analysis)** — one row per LLM call: timestamp, Δ duration, tokens in/out, cache read and cache written, cache-hit %, tools called, and cost. Click a row and you get the drill-down: the exact payload sent for that call, item by item (system / user / assistant / tool result), each labelled **cached / new-cache / fresh** with estimated tokens and a readable preview, next to the model's rendered reply. That is how you diagnose a cache loss without opening a JSON file;
- **Costs** — the cost aggregate for the run.

Nothing is ever deleted. Archiving a ticket or a conversation removes it from the board and keeps it in its store, recoverable.

### The agent builder

`/agent-builder` composes or edits a profile in three steps — **Identity**, **Capabilities**, **Prompt**: name it or load an existing one as a base, pick its tools, skills and hooks from the catalogue, write a prompt supplement, and unfold **Computed full prompt** to read exactly what the agent will receive before you save it, not after. The result is a global profile under `~/.bouzecode/profiles`, switched on in a session with `/agent <name>`. The same page installs plugins, browses the shared agent catalogue (**Installed** vs **Available**), and edits skill `.md` files on disk.

### For agents and scripts

`GET /api/schema` describes every `/api/` route with its parameters and response shape. It is **derived from the Flask URL map**, never hand-written, so it cannot describe a route that no longer exists nor miss one that was added. Read endpoints return structured JSON; `GET /api/sessions/<key>/blocks?plain=1` returns the messages as plain text for an agent to analyse. `GET /api/search?q=<words>&scope=open|all` searches the conversations themselves — the user's messages and the model's `FinalAnswer` report, thinking and raw tool results excluded — and returns each hit with its ticket and a surrounding snippet.

### Security scope

**Treat the web UI as a single-user, localhost-only developer tool.** It has the same risk profile as running a Jupyter notebook with no token:

- No authentication. No CSRF protection.
- Remote-code-execution by design (dispatching a ticket spawns an agent).
- It binds `127.0.0.1` by default. **Do not bind to `0.0.0.0`**, do not expose it through a reverse proxy.

---

## Execution modes

An agent runs in one of three environments. The choice is explicit — made by whoever launches, or by the manager when it dispatches, because only they know whether three agents are about to write into the same repository or a single one is about to touch `pyproject.toml`.

| Mode | What it provisions | When to pick it |
|---|---|---|
| `shared` | nothing — the main repository | read-only work, sole writer, short task |
| `worktree` | a dedicated git worktree, no venv | several agents writing in parallel |
| `worktree+venv` | a dedicated git worktree **and** venv | the agent touches dependencies |

Three values, not two booleans: "no worktree but a dedicated venv" is meaningless and is not representable. Splitting worktree from venv is where the latency goes — a git worktree is nearly free, a venv is a `uv sync` per agent.

A `worktree` agent inherits the base repository's venv through `VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT` and a `PATH` prefix, so it does not silently grow a gigabyte-sized venv of its own on the first `uv run`. The trade is explicit: such an agent running `uv sync` modifies the shared base venv — which is exactly why an agent that will touch dependencies belongs in `worktree+venv`.

**Collision guard.** Two `shared` agents *writing* into the same repository would overwrite each other. That is the one genuinely destructive mistake, so the server catches it: the second is switched to `worktree` and a comment on the ticket explains why. Agents that cannot write — the read-only `manager`, for instance — are not counted, since they overwrite nobody. Whether an agent can write is derived from the tools its profile actually grants, not from the name of its typology.

Worktrees live under `~/.bouzecode/worktrees/`; `BOUZECODE_WORKTREE_ROOT` carries the current one into the agent's system prompt.

---

## Configuration

### Where things live

| Path | Contents |
|---|---|
| `~/.bouzecode/config.json` | persistent settings |
| `~/.bouzecode/sessions/` | session logs (`daily/YYYY-MM-DD/`, plus `history.json`) |
| `~/.bouzecode/skills/` | your global skills |
| `~/.bouzecode/profiles/` | your global agent profiles |
| `~/.bouzecode/agent_catalog/` | the pulled shared-agent catalogue |
| `~/.bouzecode/mcp.json` | user-level MCP servers |
| `~/.bouzecode/worktrees/` | agent worktrees |
| `~/.bouzecode/web_v2/` | projects and tickets served by the web UI |
| `<project>/.bouzecode/` | per-project `skills/`, `plugins/`, `profiles/` |
| `<project>/.mcp.json` | per-project MCP servers |

Settings are read from `config.json` over the built-in defaults in `backend/core/config.py`. The ones you are most likely to touch:

| Key | Default | Meaning |
|---|---|---|
| `model` | `claude-opus-4-8` | model for new sessions |
| `max_tokens` | `64000` | output cap per turn |
| `permission_mode` | `auto` | `auto`, `accept-all` or `manual` |
| `thinking` / `thinking_mode` | `true` / `extended` | `extended` (API thinking) or `loud` (visible `<thinking>` tags) |
| `thinking_effort` | `high` | `low`, `medium`, `high`, `max` |
| `max_tool_output` | `32000` | truncation threshold for a tool result |
| `max_agent_depth` | `3` | how deep sub-agents may nest |
| `max_concurrent_agents` | `3` | parallel sub-agents per parent |
| `task_classification` | `false` | auto-route a session to a profile from its first prompt |
| `extra_dirs` | `[]` | extra `.bouzecode`-structured directories, persisted across runs |

Set them from the REPL with `/config key=value`, or edit the file.

### Providers

Model routing is a pure function of the model string (`backend/agent/providers/registry.py`): `resolve_provider()` maps what you type to a provider and an API model id, so `--model sonnet` and `--model deepseek-v4-flash` both just work. An explicit `provider/model` prefix overrides the routing.

| Provider | Key | Endpoint | Models |
|---|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` | the official API, or any Anthropic-compatible gateway via `ANTHROPIC_BASE_URL` | `claude-*`, plus the `opus` / `sonnet` / `haiku` aliases |
| `openrouter` | `OPENROUTER_KEY` (or `OPENROUTER_API_KEY`) | `https://openrouter.ai/api/v1` | `deepseek-v4-flash`, `deepseek-v4-pro`, `kimi-k2.7-code`, `kimi-k3`, `glm-5.2` |
| `gateway` | `BOUZECODE_GATEWAY_API_KEY` | `BOUZECODE_GATEWAY_BASE_URL` | whatever you list in `BOUZECODE_GATEWAY_MODELS` |

The `gateway` slot is an **OpenAI-compatible endpoint of your own** — LiteLLM, vLLM, an in-house proxy. Nothing about it is hardcoded: endpoint, key and model list all come from the environment (see [Pick a provider](#pick-a-provider) for the three variables), so the provider stays inert until you point it somewhere. Model names are sent verbatim to the gateway, so they must be exactly what it expects. Per-model input/output rates and cache-read overrides live in the same file and feed the cost columns of the web UI.

**Tool-call protocol.** OpenAI-compatible providers use native function calling. Anthropic endpoints use the XML tool protocol unless you opt in with `BOUZECODE_ANTHROPIC_NATIVE_TOOLS=1` (`0` forces XML back); a profile or config that sets `xml_tools` outranks both.

### Environment variables

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | Anthropic credentials |
| `ANTHROPIC_BASE_URL` | point the Anthropic transport at a compatible gateway |
| `OPENROUTER_KEY` / `OPENROUTER_API_KEY` | OpenRouter credentials |
| `BOUZECODE_GATEWAY_BASE_URL` / `_API_KEY` / `_MODELS` | the OpenAI-compatible gateway slot |
| `EXA_KEY` | key for the Exa search API, which `WebSearch` prefers; without it the tool scrapes DuckDuckGo instead |
| `BOUZECODE_LANG` | terminal wording: any value starting with `fr` prints French, everything else English |
| `BOUZECODE_NATIVE_TOOL_ENDPOINTS` | endpoints that must use native function calling |
| `BOUZECODE_ANTHROPIC_NATIVE_TOOLS` | `1` native tool calling, `0` XML protocol |
| `BOUZECODE_ENABLE_CHROME_DEVTOOLS` | `1` loads the browser tools (same as `--enable-chrome-devtools`) |
| `BOUZECODE_CACHE_TTL_1H` | `1` requests the 1-hour prompt-cache TTL on non-official endpoints |
| `BOUZECODE_NO_PLUGINS` | skip plugin loading entirely (CI, hermetic tests) |
| `BOUZECODE_NO_ENFORCE` | disable the methodology/snippet enforcement side-calls |
| `BOUZECODE_AGENT_CATALOG_URL` / `_PATH` | git URL, or local path, of the shared agent-profile catalogue |
| `BOUZECODE_GITLAB_URL` | base URL of the GitLab instance hosting your plugins |
| `BOUZECODE_WORKTREE_ROOT` | the worktree an agent is running in, surfaced in its system prompt |
| `BOUZECODE_LAUNCH_CWD` | default working directory when `--cwd` is absent |
| `BOUZECODE_TOOL_OUTPUT_DIR` | where oversized tool outputs are spilled to disk |
| `BOUZECODE_WEB_BASE_URL` | base URL agents post their completion hook back to |
| `BOUZECODE_PROXY_URL` / `_USER` / `_PASSWORD` | outbound HTTP proxy, when your network needs one |

---

## Extending

Four extension points, in increasing order of commitment.

### Skills

A skill is a reusable prompt template: a markdown file with YAML frontmatter, exposed to the model through the `Skill` / `SkillList` / `SkillGrep` tools and to you as a slash command.

```markdown
---
name: commit
description: Stage, write a conventional commit message, and commit.
triggers: ["/commit", "commit my changes"]
tools: [Bash, Read]      # `allowed-tools` is accepted under the same meaning
scope: ""                # "" = global; a path restricts the skill to that subtree
context: inline          # `inline` runs it in the current turn, `fork` in a sub-agent
---

Read the staged diff, then …
```

Only `name` is mandatory; without `triggers` the skill answers to `/<name>`. Skills are discovered in `.bouzecode/skills/` and `.claude/skills/` of the current directory **and its ancestors** (nearest wins, which is what makes a monorepo work), then in `~/.bouzecode/skills/` and `~/.claude/skills/`, then in any `--extra-dir`.

### Agent profiles

A profile is a YAML file declaring what an agent is: its tool whitelist, its skills, its hooks, an optional model override, and a system-prompt supplement.

```yaml
name: reviewer
description: Reads a diff and reports, never edits.
tools: [Read, Glob, Grep, GetDiff]
skills: [review]
hooks: [run_completion_chain]
model: ""
system_prompt_extra: |
  You review, you do not fix. …
```

Resolution order is builtin < `~/.bouzecode/profiles/` < `<cwd>/.bouzecode/profiles/` < `--extra-dir` paths, so a project can shadow a built-in agent under the same name. An empty `tools: []` means *no restriction*; a non-empty list is applied literally, and the framework tools (`Methodology`, `Snippet`, `FinalAnswer`, `Skill`, `SkillList`, `TaskList`, `GetDiff`, `WritePlan`, `LoadProjectConfig`, `AskUserQuestion`, `AgentsMap`, `SymbolMap`) are always on top of it — a profile can never strip the discipline machinery out from under the prompt that prescribes it.

Set `BOUZECODE_AGENT_CATALOG_URL` to a git repository laid out as `profiles/*.yaml` and the catalogue pane of the agent builder — and `/agent` in the REPL — will offer its profiles for install, pulling the required plugins along with them.

### Plugins

A plugin is a pip-installable package that contributes tools. It exposes a `TOOLS` list of plain dicts, so it never imports bouzecode:

```python
TOOLS = [
    {
        "name": "QueryWarehouse",
        "description": "Run a read-only SQL query against the analytics warehouse.",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
        "func": run_query,        # (params: dict, config: dict) -> str
        "read_only": True,
        "concurrent_safe": True,
    },
]
```

Plugins install per user or per project, from a package index or from a git source, and are enabled and disabled individually. A profile may declare `requires_plugins`, and installing that profile materialises them. `BOUZECODE_NO_PLUGINS=1` skips the whole layer.

### External tool servers

Two paths, both landing in the same registry.

**MCP servers.** Declare them in `~/.bouzecode/mcp.json` or in a `.mcp.json` beside your code (same format as Claude Code's), over stdio or HTTP. They are initialised at startup and their tools are registered after the default whitelist pass, so they stay enabled:

```json
{
  "mcpServers": {
    "my-server": { "command": "npx", "args": ["-y", "@example/mcp-server"] }
  }
}
```

**chrome-devtools.** `--enable-chrome-devtools` starts a chrome-devtools MCP server per agent thread and registers its browser tools — navigate, snapshot, screenshot, evaluate. It is off by default because its schemas cost roughly 5k tokens on every turn, which contradicts the point of the project unless you actually need a browser. The always-on `EnableChromeDevtools` / `DisableChromeDevtools` pair lets the model switch them on mid-session instead. The `frontend` profile is built around them.

---

## Why this matters: input tokens are the whole bill

A coding agent that wraps a top-tier model only stays affordable if you look squarely at **where the money actually goes**.

**Output tokens are essentially free compared to input tokens.** The model emits a few hundred to a few thousand output tokens per turn. The input, though, is the **cumulative arithmetic sum** of the growing prefix re-sent on every round-trip: system prompt + tool schemas + full conversation so far + last tool result.

A back-of-the-envelope: 10k-token system prompt, 2k new input tokens per turn. Three turns already bills `10k + 12k + 14k = 36k` input tokens. A typical coding task does **50–100 tool calls**, each with a full LLM round-trip, and the provider happily charges you for every prefix re-transmission.

Money is only half of it. Each round-trip is also a queue wait. Time-to-first-token of 30–40 s under load is routine — 40 round-trips at that rate burn real wall-clock time regardless of your budget.

**Saving money = cutting round-trips.** Everything else in this README follows from that.

### Observed results

Evaluated on a handful of tasks (**n = 5**, so think orders of magnitude, not absolute numbers): usual bug fixes and feature additions on a ~100k-LoC codebase, running both systems on the same prompts.

- ~**10× reduction in tokens consumed by the top-tier model**, and total elimination of small-model consumption (typical: 1.5 M Opus + 3 M Haiku → 200k Opus, 0 Haiku).
- Roughly the same **~10× reduction in price**.
- **~3–5× reduction in wall-clock time to reach a fix**, thanks to fewer round-trips and fewer queue waits.
- Gains widen further on long sessions, thanks to context pruning.

These are ballpark figures on a small n; treat them as signals, not benchmarks.

---

## The three mechanisms

### 1. LLM turns: aim at a theoretical minimum

Pack into one turn everything that could have fit in one turn. The system prompt steers the model toward a three-phase workflow that targets **3 LLM turns as the floor** for a complete task:

- **Phase 1 — READ**: `Read`, `Glob`, `Grep`, `GetFolderDescription`, `Skill(...)` in a single parallel batch
- **Phase 2 — PLAN**: one `WritePlan` call freezing the complete plan
- **Phase 3 — EXECUTE**: edits + tests + diagnostics in one block, ordered via `depends_on`

The DAG executor (`backend/agent/dag.py`) builds a dependency graph from the `depends_on` declarations and executes tools level by level, in parallel within each level, inside a single turn.

### 2. Pre-indexed exploration

`GetFolderDescription` replaces the serial "Explore sub-agent" pattern — which typically burns tens of thousands of tokens — with a native tool that returns an annotated file tree in a few hundred. Descriptions are auto-generated and auto-maintained through write hooks. `AgentsMap` and `SymbolMap` extend the same idea to a per-folder map of the repository and its symbols, so finding a function costs a lookup rather than a grep sweep.

### 3. The model prunes its own context

The model marks stale tool results for removal (`trash`), keeps only the relevant slices (`Snippet` freezes line ranges of a tool result), and maintains a named scratchpad (the append-only `Methodology` note). The context stays **flat** instead of inflating turn after turn. Enforcement side-calls make the bookkeeping non-optional: an un-snippeted read or a missing methodology entry is recovered before the next turn rather than left to drift.

### Bonus: hunting recurring mistakes

Observe the mistakes the model makes systematically and prevent them via prompt or tool defaults. Examples: switching `Grep`'s default to `content` mode, steering away from `python -c` on Windows, forbidding pointless re-reads, converting `Read`'s 0-indexed `offset`/`limit` from the 1-indexed `ranges` the model keeps typing.

### Further directions

Untested ideas left open:

- **Pre-reads by a smaller model.** Have scoping `Read`s executed by a mid-tier model, which returns only relevant extracts to the top-tier one.
- **System prompt caching.** Provider-dependent; estimated ~30% additional saving with shared prompts.
- **Broader recurring error catalogue.** Continuous observation work that depends on stack-specific LLM mistakes.

---

## Architecture

```
bouzecode/
├── src/
│   ├── bouzecode/
│   │   ├── backend/                  # the engine
│   │   │   ├── agent/                # turn loop, tool DAG, streaming, compaction, thinking
│   │   │   │   ├── hooks/            # the completion-hook pipeline
│   │   │   │   └── providers/        # provider registry + streaming backends
│   │   │   ├── checkpoint/           # file backups and conversation snapshots
│   │   │   ├── chrome_devtools/      # opt-in chrome-devtools MCP client
│   │   │   ├── commands/             # REPL slash commands (+ oss_shims/)
│   │   │   ├── context_manager/      # methodology note, snippets, notes, compaction
│   │   │   ├── core/                 # config, paths, tool registry, system-prompt assembly
│   │   │   ├── multi_agent/          # sub-agent spawning, isolation, message queues
│   │   │   ├── plugin/               # pip-installable extensions
│   │   │   ├── profiles/             # agent profiles: builtin/, discovery, composer, catalog
│   │   │   ├── tools/                # built-in tools + ops/, agents_map/, folder_desc/,
│   │   │   │                         #   skill/, task/, projects_tool/
│   │   │   └── xml_tool_protocol/    # text tool-call protocol (parser, emitter, docs)
│   │   ├── ui/                       # terminal front end: CLI, REPL, rendering, replay
│   │   └── web_v2/                   # Flask web UI
│   │       ├── routes/               # JSON API blueprints
│   │       ├── services/             # business logic, Flask-free and independently testable
│   │       ├── runtime/              # agent lifecycle: runner, IPC, warm pool, context viewer
│   │       ├── templates/            # conversations, session, agent-builder
│   │       └── static/               # dark-theme CSS, ES modules, vendored Monaco (no CDN)
│   └── system_prompts/               # the prompt fragments, shipped inside the wheel
├── memory/  mcp/  voice/  video/  plugin/  html_renderer/  …   # see Subsystems
├── readme_sync/                      # keeps the folder README maps in step with the code
├── docs/                             # this documentation and the project pages
├── tests/                            # the test suite
├── bouzecode.ps1  bouzegui.ps1       # Windows launchers (pure ASCII, .env before install)
├── load_dotenv.ps1                   # the .env reader they share
└── bouzecode_publish.ps1  bouzecode_self_update.ps1
```

### Core loop

1. User prompt → tool protocol (native function calling or XML, per provider) → the model emits tool calls
2. The DAG executor builds a dependency graph from the `depends_on` declarations
3. Tools execute level by level, in parallel within each level
4. Results are injected back into the context → next turn

### The toolset

46 tools are registered. Not all are sent to the model: the framework tools plus a default work set are enabled at import, and the rest are switched on by an agent profile, by `/tools enable`, or by an extension.

| Group | Tools |
|---|---|
| Files & shell | `Read` `Write` `Edit` `NotebookEdit` `Bash` `BashOutput` `Glob` `Grep` `RunPythonTest` `GetDiagnostics` `GetDiff` |
| Navigation | `GetFolderDescription` `AgentsMap` `SymbolMap` |
| Context discipline | `Methodology` `Snippet` `FinalAnswer` |
| Planning & tasks | `WritePlan` `EnterPlanMode` `ExitPlanMode` `TaskCreate` `TaskUpdate` `TaskGet` `TaskList` |
| Skills | `Skill` `SkillList` `SkillGrep` |
| Memory | `MemorySave` `MemoryList` `MemorySearch` `MemoryDelete` |
| Fleet | `Agent` `MessageAgent` `SendMessage` `CheckAgentResult` `ListAgentTasks` `ListAgentTypes` `Fleet` |
| Web | `WebFetch` `WebSearch` |
| Interaction | `AskUserQuestion` `SleepTimer` |
| Projects | `AddProject` `LoadProjectConfig` |
| Browser (opt-in) | `EnableChromeDevtools` `DisableChromeDevtools` + the chrome-devtools tools |

Enabled by default: the twelve framework tools (`Methodology`, `Snippet`, `FinalAnswer`, `Skill`, `SkillList`, `TaskList`, `GetDiff`, `WritePlan`, `LoadProjectConfig`, `AskUserQuestion`, `AgentsMap`, `SymbolMap`) plus `Read`, `Write`, `Edit`, `Bash`, `BashOutput`, `Glob`, `Grep`, `RunPythonTest`, `WebFetch`, `WebSearch`, `AddProject`, `MemorySave`, `MemoryList` — and the chrome-devtools bootstrap pair. MCP tools join them when a server is configured.

---

## Tests

The suite runs against a scripted model. A hermetic guard in `tests/conftest.py` **blocks any real LLM call** unless a test explicitly opts in, so a missing key can never turn into a surprise bill.

```powershell
uv pip install -e ".[test]"
.venv\Scripts\python.exe -m pytest -q                        # the whole suite
.venv\Scripts\python.exe -m pytest -q -n auto                # parallel, via pytest-xdist
.venv\Scripts\python.exe -m pytest -q -m backend             # the engine only
.venv\Scripts\python.exe -m pytest -q tests\web_v2           # the web service layer
```
```bash
uv pip install -e ".[test]"
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q -n auto
.venv/bin/python -m pytest -q -m backend
.venv/bin/python -m pytest -q tests/web_v2
```

`testpaths` is `tests/`, `readme_sync/tests/` and four trees under `src/` that live beside the code they cover (`backend/tests/`, `backend/agent/providers/backends/tests/`, `web_v2/runtime/tests/`, `web_v2/tests/`). Every test is auto-marked from the folder it lives in: `tests/backend/` → `backend`, `tests/ui/` → `ui`, `tests/web_v2/` and `src/bouzecode/web_v2/tests/` → `web`. A fourth marker, `slow`, tags the fixture files the test-runner tests target. Nothing under `src/` is collected implicitly: each tree is named, and each is excluded from the wheel by `packages.find.exclude`, so tests are run from the checkout and never installed.

The front-end JavaScript has a suite of its own, under `src/bouzecode/web_v2/tests/js/`: the real `static/js/` modules loaded into a simulated DOM (happy-dom) and driven through clicks and events, no browser involved.

```bash
cd src/bouzecode/web_v2
npm install
npm test
```

`tests/backend/TEST_METHODOLOGY.md` states the policy. In short: **a test must be readable without opening the code it tests** — you read it as a story, *the user asks X, the agent does Y, we observe Z*. The suite is therefore dominated by conversation tests, which drive the agent the way a human would, rather than unit tests of internal functions. Four levels, always take the highest that suffices:

1. **`mock_llm`** — the default, ~90% of cases. Only the model's replies are scripted; the loop, the tools, the enforcement and the methodology all run for real. No network, no browser.
2. **`mock_api`** — transport only. A fake SSE server with the real client pointed at it: wire serialisation, SSE parsing, `cache_control`, retries. Slow — one server per call.
3. **Flask test client** — the default for `web_v2`. HTTP behaviour, JSON, status codes, observable server-side effects, no browser.
4. **Playwright** — last resort, strictly for what only a real DOM proves: streaming rendering, real user interaction, repaint order.

The JavaScript suite sits between the last two: it exercises the real front-end scripts with real events, which is what keeps the Playwright level as small as the policy demands.

---

## Contributing

Two documents to read before writing anything:

- **the folder `README.md` maps** — every code folder carries one, stating its purpose, its subfolders and its symbols. It is the shortest path to a function without grepping. `python -m readme_sync --check` walks the tree and exits 0 when every map matches its code; `--list-stale` names the ones that drifted, `--regen` rebuilds one. The filename is a setting rather than a constant — `--doc-name`, the `README_SYNC_DOC_NAME` variable, or `[tool.readme_sync] doc_name` in `pyproject.toml`, most specific first — so the same tool maintains an `AGENTS.md` tree elsewhere; here it is `README.md`.
- **`tests/backend/TEST_METHODOLOGY.md`** — the four-level test policy above.

Where to change what:

| You want to change | Start here |
|---|---|
| A slash command | `backend/commands/dispatcher.py` — the `COMMANDS` table and its handlers |
| A command backed by a flat package | `backend/commands/oss_shims/` |
| The turn loop, streaming, enforcement | `backend/agent/loop.py`, `loop_turn.py`, `dag.py` |
| A tool's schema or behaviour | `backend/tools/schemas.py` + `backend/tools/ops/` |
| Which tools exist at all | `backend/core/tool_registry.py` and `backend/tools/registration.py` |
| A model, a price, a routing rule | `backend/agent/providers/registry.py` |
| The system prompt | `backend/core/context.py` and `src/system_prompts/` |
| A built-in agent | `backend/profiles/builtin/*.yaml` |
| A web page or endpoint | `web_v2/routes/` (HTTP) then `web_v2/services/` (logic) |

Three conventions worth knowing: the API schema is derived from the URL map rather than written by hand; the web UI never parses stdout — if you need something displayed, emit it into the structured session JSON; and every `.ps1` at the root is **pure ASCII**, since Windows PowerShell 5.1 re-reads a BOM-less script as ANSI and mangles anything above 127. A test walks the launchers and fails on the first non-ASCII byte, and on any launcher that installs dependencies before loading `.env`.

Further reading in [`docs/`](./docs/): [architecture](./docs/architecture.md) — the shape of the code and the rules that hold it together — and the [contributor guide](./docs/contributor_guide.md), which maps every "I need to change X" onto the file that owns it.

---

## Credit

Base: [**CheetahCode / Nano Claude Code**](https://github.com/SafeRL-Lab/clawspring) (SafeRL-Lab). Original project license preserved ([LICENSE](./LICENSE)).

---

## License

Apache-2.0. See [LICENSE](./LICENSE).
