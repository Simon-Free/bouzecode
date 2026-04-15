# Bouzecode

> A fork of [**CheetahCode**](https://github.com/SafeRL-Lab/clawspring) (Nano Claude Code) by BouzéLab, itself inspired by Claude Code.

**This project is a PoC.** What matters here are the **ideas** for shrinking the token cost of a code agent *at equal model capability* — not the implementation quality, which is honestly rough, because we didn't really have the time to polish it. If an idea speaks to you, feel free to re-implement it cleanly in your own stack. That said, if you have any LLM agent on hand to assist you, getting this PoC to run on your own infra shouldn't be too hard.

The angle is strict: **reduce the number of tokens consumed without degrading the reasoning capability** of the underlying model. We therefore deliberately avoid downgrades to smaller models, and only work on the *shape* of the context sent to Opus 4.6.

---

## Install

### Prerequisites

- **Python** ≥ 3.11 (3.13 recommended, matches what we test against).
- **[uv](https://astral.sh/uv)** — used for venv + dependency resolution. Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
- **ripgrep (`rg`)** — highly recommended; bouzecode's `Grep` tool falls back to a slow Python implementation without it. Install via `brew install ripgrep`, `apt install ripgrep`, or `winget install BurntSushi.ripgrep.MSVC`.
- An **Anthropic API key** in `ANTHROPIC_API_KEY` (other providers — OpenAI, Gemini, DeepSeek, etc. — are wired up in `providers/registry.py` with their own env vars).

### Windows (one-shot launchers)

```powershell
git clone https://github.com/<you>/bouzecode.git
cd bouzecode
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # or put it in a .env file
.\bouzecode.ps1                          # launches the REPL
.\bouzegui.ps1                           # launches BouzéGUI on http://127.0.0.1:5055
```

`bouzecode.ps1` and `bouzegui.ps1` handle venv creation, dependency sync, ripgrep install, and `.env` loading automatically.

### macOS / Linux (manual)

```bash
git clone https://github.com/<you>/bouzecode.git
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

## Why this matters: input tokens are the whole bill

A coding agent that wraps Opus 4.6 (via AWS Bedrock or any other provider) only stays affordable if you look squarely at **where the money actually goes**.

**Output tokens are essentially free compared to input tokens.** The model emits a few hundred to a few thousand output tokens per turn. The input, though, is the **cumulative arithmetic sum** of the growing prefix re-sent on every round-trip: system prompt + tool schemas + full conversation so far + last tool result.

A back-of-the-envelope: 10k-token system prompt, 2k new input tokens per turn. Three turns already bills `10k + 12k + 14k = 36k` input tokens. A typical coding task does **50–100 tool calls**, each with a full LLM round-trip, and the provider happily charges you for every prefix re-transmission.

Money is only half of it. Each round-trip is also a queue wait. Time-to-first-token of 30–40 s under load is routine — 40 round-trips at that rate burn real wall-clock time regardless of your budget.

**Saving money = cutting round-trips.** Everything else in this README follows from that.

### The minimum viable loop

An orchestrated code agent ideally reasons in 3 (no human validation) or 4 steps:

1. **Locate** the relevant code.
2. **Read** it.
3. **Plan** (optionally gated by a human).
4. **Write** edits, then run tests / lint / diagnostics.

Each step genuinely needs the previous one — you cannot read without knowing what to read, cannot plan / write / test without having read. The loop may iterate when later modifications depend on earlier execution results, but within one pass, **4 LLM turns is the floor** (3 if there is no human gate in the loop). Most agents blow past that floor by accident, not by necessity, and that is the gap this PoC targets.

### Observed results

Evaluated on a handful of internal tasks (**n = 5**, so think orders of magnitude, not absolute numbers): usual bug fixes and feature additions (neither trivial nor full-repo refactors — sub-agent-heavy workloads remain to be characterised) on a ~100k-LoC codebase, running both systems on the same prompts.

- ~**10x reduction in tokens consumed by the top-tier model**, and total elimination of small-model consumption (typical: 1.5 M Opus + 3 M Haiku → 200k Opus, 0 Haiku) for the same task, on the very first request — before the model even starts diagnosing, we save the full cycle of an `Explore` sub-agent.
- Roughly the same **~10x reduction in price**.
- **~3-5x reduction in wall-clock time to reach a fix**, thanks to fewer round-trips and fewer queue waits.
- Gains widen further on long sessions, thanks to the context pruning described below.

These are ballpark figures on a small n; treat them as signals, not benchmarks.

There is one honest tradeoff on the time axis. Providers like AWS Bedrock transparently cache the growing conversation prefix so that each follow-up call re-ingests only the new tail (you still get billed for the full prefix, but you save the processing time). `ContextGC` deliberately **rewrites mid-history every turn** — stubs, snippets, notes inserted at the top of the last user message — which invalidates that cache by construction. Per-call TTFT is therefore often *worse* than vanilla. Write throughput in Phase 3 (edits, test runs, diagnostics) stays constant — there is no free lunch there either. The only reason the wall-clock still comes out ~3–5x ahead is that **we make so many fewer LLM calls overall** that the per-call penalty is paid a handful of times instead of dozens.

Three mechanisms combine to get there.

---

## 1. LLM turns: aim at a theoretical minimum

The LLM turn is the most expensive resource in the system. For a looping agent, the easiest saving is to **pack into one turn everything that could have fit in one turn**. `system_prompt_template.txt` frames this as an ideal — the *3-Phase Workflow* — rather than a hard constraint: the model stays free to deviate when it needs to, but it knows the theoretical floor it is shooting for.

- **Phase 1 — READ**: `Read`, `Glob`, `Grep`, `WebFetch`, `GetFolderDescription`, `Skill(...)` are grouped in a single parallel batch. The prompt explicitly encourages reading *more* files than strictly needed — one extra `Read` costs a fraction of a turn, an extra LLM round-trip costs a whole one.
- **Phase 2 — PLAN**: a single `WritePlan` call that freezes the complete plan before any edit.
- **Phase 3 — EXECUTE**: source edits, test edits, `GetDiagnostics`, and `pytest` execution all go out in one block, ordered via `tool_call_alias` / `depends_on`.

The "3 turns max" rule is an objective, not a hard cap. What matters is that framing it this way pushes the model to **pre-declare its dependencies** rather than serialise them over time.

### The execution engine and cross-tool dependencies

The runtime (`agent/dag.py` + `agent/loop.py`) builds a DAG from the `depends_on` declared in the same turn, then executes calls **level by level, parallelising whatever can be parallelised**. This lets the model express, in a single turn, useful chains like:

- write a throwaway script (`Write(alias="w1")`), then execute it (`Bash(depends_on=["w1"])`);
- edit several files in parallel, then launch `pytest` which depends on all edits;
- chain `Edit` + `GetDiagnostics` on the same file (implicit dependency auto-injected by the runtime).

Without this machinery, each of those sequences costs *N* LLM turns where it can cost one.

## 2. `GetFolderDescription`: pre-indexed exploration, no serial `Explore` agent

The most common way to explore a repo with an AI agent is to delegate to an `Explore` sub-agent that loops on its own `Grep` / `Read` and eventually returns a summary. It is one of the heaviest line items on an average task — tens of thousands of tokens spent purely to figure out *where things live*.

Bouzecode replaces that pattern with a native tool, **`GetFolderDescription`** (`folder_desc/tools.py`), which returns an annotated file tree:

```
web/
  app.py             -- Flask entrypoint, HTTP routes, blueprint mounting.
  runner.py          -- Orchestrates agent runs in a thread, SSE to the frontend.
  session_service.py -- Persistence / resume of conversational sessions.
  ...
```

Each one-line description comes from a `[desc] ... [/desc]` tag at the top of the file — the same pattern as Skills' `description:`.

- Existing descriptions are read and returned as-is.
- **Missing descriptions are all generated** on the fly through a parallel LLM pass (one call per file, in parallel) before the tree is returned. The intent is that the tree is *always* complete — any file without a description is an indexing bug.
- A `Write` hook (`_install_write_hook`) automatically updates the `[desc]` line after each edit, so descriptions do not drift from the code.

In practice, the model does not wait for `GetFolderDescription` to return before deciding where to look: it fires `Glob` / `Grep` / `Read` **in the same parallel batch** as `GetFolderDescription`, based on whatever the user's prompt already hints at. The condensed overview — a few hundred tokens — then lands alongside those results. When the early guess was enough, the model skips straight to a focused second `Read` batch (if even needed) and the task finishes in 3 turns. When it wasn't, the folder description repositions the next `Read` batch without a dedicated exploration round-trip. Either way, no serial `Explore` sub-agent, no thousands of tokens spent locating files.

## 3. `ContextGC`: the model prunes its own context

New tool added in this fork (`context_gc.py` + entry in `tools/schemas.py`). The system prompt makes it mandatory on every turn that contains tool calls:

> After EVERY assistant turn that includes tool calls, you MUST include a `ContextGC` call in the same tool batch.

`ContextGC` takes four parameters:

- **`trash`**: list of `tool_call_id`s to discard entirely. Their content is replaced by a stub `[X result -- trashed by model]`. Typically: a large `Read` already consumed, a `Grep` from which the useful part has been extracted.
- **`keep_snippets`**: keep only a slice of a large result, using **textual anchors** (`keep_after`, `keep_before`, `keep_between`). Cut lines are replaced by a marker `[N lines trimmed before 'X']`.
- **`notes`**: **named scratchpad, persistent across turns**. This is where the model stores what it wants to *keep*: a key file path, a function signature, a concise reason for a tool-call failure (instead of dragging 8 KB of traceback around), a TODO list, an architectural decision. Each note is named, overwritable, and independently removable.
- **`trash_notes`**: explicit removal of notes that are no longer relevant.

On every turn, before the API call, `followup_compaction.build_messages_for_api`:

1. applies standard follow-up compaction;
2. applies the accumulated `ContextGC` decisions (stubs + snippets);
3. injects the active notes at the top of the last user message, as a working memory that is always present.

The effect is both immediate (starting from the next turn within the same question) and cumulative on long sessions: the context sent to the API stays **flat** instead of inflating turn after turn.

## Hunting down the model's recurring mistakes

At equal model capability, a non-trivial share of the savings comes from more down-to-earth work: **observe the mistakes the model makes systematically and prevent them via the prompt or tool defaults**. A few concrete examples from our traces:

- **Grep**: the default was switched from `files_with_matches` to `content`. The model *expects* `content` — it reasons as if the match itself is already there, and with the old default it would systematically burn one extra round-trip re-running the same `Grep` with `output_mode="content"`, or chaining a `Read` on the returned filename. Aligning the default with the model's implicit expectation kills that extra turn outright.
- **Python from Bash on Windows**: models handle multi-line `python -c "…"` poorly on this platform. Rather than fixing downstream, the prompt steers them toward writing a script file and then executing it — which goes through the `tool_call_alias` / `depends_on` plumbing described above.
- **Pointless re-reads**: the prompt forbids `Read`ing a file we just wrote, or doing a separate "check syntax" turn before `pytest`. 

Every recurring error pattern spotted and fixed removes a fraction of "correction turns" which, added up, weigh heavily on the final bill.

---

## Further directions

This PoC leaves several levers open — all ideas below are **untested** at this point:

- **Pre-reads by a smaller model.** Have scoping `Read`s executed by Sonnet or Haiku, which returns only the relevant extracts to Opus. Intuitively promising, but the trade-off is not obvious: Opus may miss information the small model did not deem useful. To benchmark.
- **System prompt caching.** The implementation depends on the provider and model, and is therefore out of scope for a generic PoC — to be adapted at the fork level. But on our test tasks we were running at ~60k input tokens per turn, ~20k of which were system prompt; with a one-hour cache and several users sharing the same prompt, we estimate an additional ~30% saving.
- **Broaden the catalogue of recurring errors tracked.** This is continuous observation work that benefits every task directly, but depends on the specific errors the LLM is making on your stack. 

---

## BouzéGUI — the sidecar web UI

`web/` contains **BouzéGUI**, a small Flask app that launches via `bouzegui` (or `bouzegui.ps1` on Windows) and opens on `http://127.0.0.1:5055`. It was not part of the original PoC goal — it started as a side quest because debugging long agent runs from the terminal alone was painful. It lets you:

- browse current / finished agents and their live stdout,
- inspect the plan and the edited-files diff for each run,
- view / edit skills on disk,
- list the registered tools.

It is useful, but it is a debugging aid — **not** a hardened multi-user product.

### Security scope

**Treat BouzéGUI as a single-user, localhost-only developer tool.** It has the same risk profile as running a Jupyter notebook with no token:

- **No authentication.** Any process that can reach the port hits every route.
- **Remote-code-execution by design.** `POST /agents/new` takes a `cwd` form field and spawns a bouzecode agent there; the agent then has access to `Write` / `Edit` / `Bash`. Anyone who can POST to this endpoint can execute arbitrary code under your account.
- **No CSRF protection.** A malicious webpage loaded in your browser can forge requests to `http://127.0.0.1:5055/...` even though the server is localhost-only.
- **Skill editing writes to disk** via `POST /skills/<name>/save`.

Practical consequences: **do not bind BouzéGUI to `0.0.0.0`**, do not expose it through a reverse proxy, do not run it on a shared machine, and assume that anything running under your user account (including browser tabs) can drive it. If those assumptions do not hold for you, wrap it behind auth before use.

---

## Credit

Base: [**CheetahCode / Nano Claude Code**](https://github.com/SafeRL-Lab/clawspring) (SafeRL-Lab). Original project license preserved ([LICENSE](./LICENSE)).

Tests covering the mechanisms specific to this fork:

- `tests/test_context_gc.py` — trash / snippets / notes / injection
- `tests/test_followup_compaction.py` — compaction + GC integration
- `tests/test_write_plan_ipc.py` — multi-plan accumulation
