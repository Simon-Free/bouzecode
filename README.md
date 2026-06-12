# Bouzecode

> A fork of [**CheetahCode**](https://github.com/SafeRL-Lab/clawspring) (Nano Claude Code) by BouzéLab, itself inspired by Claude Code.

**This project is a PoC.** What matters here are the **ideas** for shrinking the token cost of a code agent *at equal model capability* — not the implementation quality, which is honestly rough, because we didn't really have the time to polish it. If an idea speaks to you, feel free to re-implement it cleanly in your own stack.

The angle is strict: **reduce the number of tokens consumed without degrading the reasoning capability** of the underlying model. We therefore deliberately avoid downgrades to smaller models, and only work on the *shape* of the context sent to Opus 4.6.

---

## 🎯 Interactive Presentation

**[▶ View the interactive presentation — Token savings explained](https://simon-free.github.io/bouzecode/)**

A visual walkthrough of how Bouzecode achieves ~10× token reduction in agentic coding workflows.

---

## Install

### Prerequisites

- **Python** ≥ 3.11 (3.13 recommended, matches what we test against).
- **[uv](https://astral.sh/uv)** — used for venv + dependency resolution. Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
- **ripgrep (`rg`)** — highly recommended; bouzecode's `Grep` tool falls back to a slow Python implementation without it. Install via `brew install ripgrep`, `apt install ripgrep`, or `winget install BurntSushi.ripgrep.MSVC`.
- An **Anthropic API key** in `ANTHROPIC_API_KEY` (other providers — OpenAI, Gemini, DeepSeek, etc. — are wired up in `providers/registry.py` with their own env vars).

### Windows (one-shot launchers)

```powershell
git clone https://github.com/Simon-Free/bouzecode.git
cd bouzecode
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # or put it in a .env file
.\bouzecode.ps1                          # launches the REPL
.\bouzegui.ps1                           # launches BouzéGUI on http://127.0.0.1:5055
```

`bouzecode.ps1` and `bouzegui.ps1` handle venv creation, dependency sync, ripgrep install, and `.env` loading automatically.

### macOS / Linux (manual)

```bash
git clone https://github.com/Simon-Free/bouzecode.git
cd bouzecode
uv venv --python 3.13
uv pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/bouzecode       # REPL
.venv/bin/bouzegui        # BouzéGUI web UI
```

A `.env` file at the repo root is picked up automatically on Windows; on Linux/macOS either `source` it or export the variables yourself.

### Verify

From a fresh clone, `uv pip install -e .` should pull in anthropic / openai / flask / rich / markdown / psutil, and install two entry-point scripts (`bouzecode` and `bouzegui`) into `.venv/Scripts/` (Windows) or `.venv/bin/` (Unix). That is the full install — there is no compiled step, no external service to wire up beyond the API key.

---

## Architecture

```
src/bouzecode/
├── backend/          # Engine core: agent loop, DAG executor, providers, tools, sessions
│   ├── agent/        # Agent loop, methodology, enforcement, context GC
│   ├── providers/    # LLM provider registry (Anthropic, OpenAI, Gemini, DeepSeek, Bedrock)
│   ├── tools/        # Tool runner, schemas, plan mode, diagnostics
│   └── sessions/     # Session persistence, checkpoint, resume
├── ui/               # Terminal UI (CLI display, paste input)
├── web/              # Internal web IPC layer
└── web_v2/           # Web V2 server (FastAPI/Starlette, WebSocket, streaming)

xml_tool_protocol/    # XML tool-call protocol (parser, emitter, docs generation)
agent/                # High-level agent orchestration, DAG scheduling
tools/                # Tool implementations (Read, Write, Edit, Bash, Grep, Glob, etc.)
folder_desc/          # GetFolderDescription tool (pre-indexed exploration)
skill/                # Skill system (reusable prompt templates)
task/                 # Task management (multi-step plans)
memory/               # Persistent memory (notes across sessions)
plugin/               # Plugin loading system
mcp/                  # Model Context Protocol (stdio transport, JSON-RPC)
voice/                # /voice command (TTS/STT sentinel flow)
video/                # Video generation pipeline (mocked shim)
multi_agent/          # Multi-agent orchestration
html_renderer/        # Session export to HTML
web/                  # BouzéGUI (Flask sidecar for debugging)
tests/                # ~1434 tests (pytest)
```

### Core loop

1. User prompt → XML tool-call protocol → LLM generates `<tool_use>` blocks
2. DAG executor (`agent/dag.py`) builds dependency graph from `depends_on` declarations
3. Tools execute level-by-level (parallel within each level)
4. Results injected back into context → next LLM turn

### Key mechanism: 3-phase workflow

The system prompt steers the model toward a minimum-turn workflow:

- **Phase 1 — READ**: `Read`, `Glob`, `Grep`, `GetFolderDescription`, `Skill(...)` in a single parallel batch
- **Phase 2 — PLAN**: one `WritePlan` call freezing the complete plan
- **Phase 3 — EXECUTE**: edits + tests + diagnostics in one block, ordered via `depends_on`

---

## Features

| Category | Feature | Description |
|----------|---------|-------------|
| **Engine** | DAG executor | Parallel tool execution with `depends_on` scheduling |
| **Engine** | Context GC | Model-driven context pruning (trash, snippets, notes) |
| **Engine** | GetFolderDescription | Pre-indexed directory exploration, no serial sub-agent |
| **Engine** | Methodology & Enforcement | Persistent working memory, mandatory tool-call discipline |
| **Engine** | Multi-provider | Anthropic, OpenAI, Gemini, DeepSeek, AWS Bedrock |
| **Tools** | XML tool protocol | Streaming parser, tool docs generation, typed schemas |
| **Tools** | Read/Write/Edit/Bash/Grep/Glob | Standard filesystem + shell tools |
| **Tools** | WritePlan | Human-gated planning with UI tab |
| **Tools** | GetDiagnostics | LSP-style diagnostics post-edit |
| **Subsystems** | Skills | Reusable prompt templates with triggers |
| **Subsystems** | Tasks | Multi-step plan management |
| **Subsystems** | Memory | Persistent notes across sessions |
| **Subsystems** | Plugins | Dynamic tool/command loading |
| **Subsystems** | MCP | Model Context Protocol server management (stdio) |
| **Integrations** | Voice | /voice command with TTS/STT sentinel |
| **Integrations** | Video | Video generation pipeline (shim) |
| **Integrations** | Telegram | /telegram command + proactive sentinel |
| **Integrations** | Multi-agent | Orchestrated sub-agents |
| **UI** | Terminal REPL | Rich CLI with streaming display |
| **UI** | BouzéGUI | Flask web UI (agent browser, plan/diff viewer, skill editor) |
| **UI** | Web V2 | FastAPI/Starlette server with WebSocket streaming |
| **Export** | HTML renderer | Session export to standalone HTML |

---

## Why this matters: input tokens are the whole bill

A coding agent that wraps Opus 4.6 only stays affordable if you look squarely at **where the money actually goes**.

**Output tokens are essentially free compared to input tokens.** The model emits a few hundred to a few thousand output tokens per turn. The input, though, is the **cumulative arithmetic sum** of the growing prefix re-sent on every round-trip: system prompt + tool schemas + full conversation so far + last tool result.

A back-of-the-envelope: 10k-token system prompt, 2k new input tokens per turn. Three turns already bills `10k + 12k + 14k = 36k` input tokens. A typical coding task does **50–100 tool calls**, each with a full LLM round-trip, and the provider happily charges you for every prefix re-transmission.

Money is only half of it. Each round-trip is also a queue wait. Time-to-first-token of 30–40 s under load is routine — 40 round-trips at that rate burn real wall-clock time regardless of your budget.

**Saving money = cutting round-trips.** Everything else in this README follows from that.

### Observed results

Evaluated on a handful of internal tasks (**n = 5**, so think orders of magnitude, not absolute numbers): usual bug fixes and feature additions on a ~100k-LoC codebase, running both systems on the same prompts.

- ~**10× reduction in tokens consumed by the top-tier model**, and total elimination of small-model consumption (typical: 1.5 M Opus + 3 M Haiku → 200k Opus, 0 Haiku).
- Roughly the same **~10× reduction in price**.
- **~3–5× reduction in wall-clock time to reach a fix**, thanks to fewer round-trips and fewer queue waits.
- Gains widen further on long sessions, thanks to context pruning.

These are ballpark figures on a small n; treat them as signals, not benchmarks.

---

## The three mechanisms

### 1. LLM turns: aim at a theoretical minimum

Pack into one turn everything that could have fit in one turn. The 3-Phase Workflow (READ → PLAN → EXECUTE) targets **3 LLM turns as the floor** for a complete task. The DAG executor (`agent/dag.py`) builds a dependency graph from `depends_on` declarations and executes tools level-by-level in parallel within a single turn.

### 2. GetFolderDescription: pre-indexed exploration

Replaces the serial "Explore sub-agent" pattern (which typically burns tens of thousands of tokens) with a native tool that returns an annotated file tree in a few hundred tokens. Descriptions are auto-generated and auto-maintained via write hooks.

### 3. ContextGC: the model prunes its own context

The model marks stale tool results for removal (`trash`), keeps only relevant slices (`keep_snippets`), and maintains a named scratchpad (`notes`). The context stays **flat** instead of inflating turn after turn.

### Bonus: hunting recurring mistakes

Observe the mistakes the model makes systematically and prevent them via prompt or tool defaults. Examples: switching Grep default to `content` mode, steering away from `python -c` on Windows, forbidding pointless re-reads.

---

## Tests

The test suite uses **mocked LLM responses** — no real API calls are needed to run tests.

```bash
# Full suite (~1434 tests, ~2 min)
python -m pytest tests/ -q

# Quick subset (skip slow subprocess tests)
python -m pytest tests/ -q -x -k "not subprocess"

# Web V2 only
python -m pytest tests/web_v2/ -q
```

Current status: **1434 tests passing** (0 failures, 44 skipped, 2 xfailed).

Test categories: agent_loop, enforcement, cache, checkpoint, DAG, methodology, thinking, tools (registry, runner, search, symbols), providers, sessions, commands, compaction, profiles, prompts, plan_mode, regression, UI, web_v2, e2e (voice, video, mcp, telegram, plugin, skill, task, memory, html_renderer, folder_desc).

---

## BouzéGUI — the sidecar web UI

`web/` contains **BouzéGUI**, a small Flask app that launches via `bouzegui` (or `bouzegui.ps1` on Windows) and opens on `http://127.0.0.1:5055`. It lets you:

- browse current / finished agents and their live stdout,
- inspect the plan and the edited-files diff for each run,
- view / edit skills on disk,
- list the registered tools.

### Security scope

**Treat BouzéGUI as a single-user, localhost-only developer tool.** It has the same risk profile as running a Jupyter notebook with no token:

- No authentication. No CSRF protection.
- Remote-code-execution by design (`POST /agents/new` spawns an agent).
- **Do not bind to `0.0.0.0`**, do not expose through a reverse proxy.

---

## Further directions

Untested ideas left open:

- **Pre-reads by a smaller model.** Have scoping `Read`s executed by Sonnet/Haiku, which returns only relevant extracts to Opus.
- **System prompt caching.** Provider-dependent; estimated ~30% additional saving with shared prompts.
- **Broader recurring error catalogue.** Continuous observation work that depends on stack-specific LLM mistakes.

---

## Credit

Base: [**CheetahCode / Nano Claude Code**](https://github.com/SafeRL-Lab/clawspring) (SafeRL-Lab). Original project license preserved ([LICENSE](./LICENSE)).

---

## License

See [LICENSE](./LICENSE).
