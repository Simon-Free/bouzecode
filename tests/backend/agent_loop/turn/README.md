# agent_loop/turn/

## Purpose
Tests of what happens within one turn of `bouzecode.backend.agent.loop`: an
interrupted turn, a stream cut short, end-of-turn detection over a tool batch, and
import safety on the first turn. Two files drive `loop.run` (or the `bouzecode()`
harness) with a `MockLLM`, two are pure unit tests.

## Usage
- `test_interrupted_context.py` — a Ctrl+C interruption records an interrupted message, `minimal_payload.build_minimal_payload` injects it into the next payload only, and a fresh `loop.run` cleans older ones.
- `test_truncated_stream.py` — a truncated LLM stream must not drop the tool calls it already emitted nor stop the agent; conversation-level, through the harness.
- `test_ends_turn_fix.py` — `core.tool_registry.ends_turn` over a mixed batch such as `[Methodology, final_answer]` signals the end when at least one tool ends the turn; tools are registered inside a `push_local_overlay`/`pop_local_overlay` pair.
- `test_wait_ready_fix.py` — importing `loop.run` and exercising its optional `bouzecode.mcp.wait_ready` path raises no `NameError` when the module is absent.
