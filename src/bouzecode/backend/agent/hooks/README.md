# Agent Hooks (Historical)

This directory previously contained an `AgentLoopHook` pipeline (registry,
base class, and concrete hook subclasses) that was **never wired into
production**. The pipeline was designed but `install_default_hooks()` was only
called from tests — the real agent loop (`loop_turn.py`) invokes enforcement
logic directly.

The dead code was removed in June 2025.

## Real Enforcement Mechanisms

The actual enforcement lives **outside** this directory:

### 1. `handle_no_tools` recovery (`loop_turn.py`)

- **When**: after assistant turn is parsed, before execution.
- **What**: if the assistant emitted zero tool calls AND `recover_memory`
  is active with thinking available, an out-of-band side-call recovers
  Methodology from the thinking, then a continuation nudge retries (up to 3).
  If recovery is unavailable or cap reached, the session closes (BREAK).
- **Effect**: prevents "thinking-only" turns from losing working memory.
  No in-wire bounce — recovery is the sole path.

### 2. `enforce_methodology` record (`loop_turn.py`)

- **When**: after assistant turn is parsed.
- **What**: logs whether the batch includes a `Methodology` call. Does NOT
  block execution if absent.
- **Coverage gap**: ~11.6% of tool-bearing batches (176/1523 measured on Opus)
  ship without Methodology and pass silently.

### 3. Out-of-band recovery (`enforcement_call.py` + `recover_memory`)

- **When**: after parsing, before execution. **Enabled by default** for
  XML-tool models (Anthropic/Opus/Sonnet); disabled for native-tool models
  (OpenRouter). Controlled by the `recover_memory` config key in `loop.py`.
- **What**: if the model omitted Methodology or Snippet, side LLM calls
  generate them automatically (`recover_methodology`, `recover_snippets`).
- **Effect**: recovered calls are prepended/appended so working-memory
  discipline is maintained even when the model forgets.

### Snippet threshold

`SNIPPET_MIN_LINES` (defined in `snippet_wire.py`, currently **50**). Results
shorter than this are never subject to Snippet enforcement.
