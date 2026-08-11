# thinking/overflow/

## Purpose

Covers the guard that cuts a model reasoning past its budget: the budget computation
(`agent.overflow_budget`), the cut itself inside `agent.loop_turn.stream_llm_turn`, the nudge
injected afterwards, and the persistence of the summarized reasoning. Also holds the checks
that tool XML written inside a thinking block is invisible to the tool parser and to the
session renderer.

## Usage

- `test_dynamic_overflow_budget.py` — `agent.overflow_budget` against `core.config.DEFAULTS`:
  floor when no prior LLM turn, zero disables overflow, scaling with context cost, hard cap,
  most recent LLM turn wins over tool entries.
- `test_thinking_overflow.py` — the `LoopContext` overflow field, the limit in `DEFAULTS`, the
  loud flag in `web_v2.runtime.runner._bouzecode_launch_cmd`, and `stream_llm_turn` firing the cut.
- `test_thinking_overflow_loud.py` — overflow driven by `TextChunk` accumulation in loud mode,
  and the bypass when the turn already carries tool calls.
- `test_thinking_overflow_nudge.py` — the message injected after a cut starts with `</thinking>`
  and carries the required keywords; driven through `agent.loop.run`.
- `test_thinking_blocks.py` — `XmlToolStreamParser`, `_is_in_thinking`, and the html renderer's
  `parse_session` / `strip_tool_xml` all ignore tool XML nested in a thinking block.
- `test_thinking_e2e.py` — the widest file: parser, `LoopDetector`, `strip_thinking_tags`, the
  agent loop over a fake stream, and the CLI flags that switch thinking mode.
- `test_overflow_carry_forward_e2e.py` — conversation through `tests.e2e_harness.bouzecode` with
  `MockLLM`: after a cut turn the just-produced tool_results stay on the next wire.
- `test_overflow_summary_persist_e2e.py` — the cut reasoning is summarized and persisted to
  methodology in both loud (`TextChunk`) and extended (`ThinkingChunk`) modes.
- `test_thinking_save_e2e.py` — spies on `agent.loop._build_assistant_content` during a real
  conversation: streamed thinking reaches it and is archived, while the wire copy is stripped.
