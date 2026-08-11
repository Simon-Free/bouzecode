# methodology/ends_turn/

## Purpose
Tests of the turn-termination decision for a meta-only tool batch: `core.tool_registry`
(`get_tool`, `ends_turn`), `agent.loop_turn.execute_tool_calls` and its `TurnAction`,
plus `agent.minimal_payload.build_messages_for_api` on the resulting message list.
Unit tests drive a hand-built `LoopContext` / `AgentState`; one file drives a real
`bouzecode()` conversation.

## Usage
- `test_meta_only_breaks_loop.py` — `execute_tool_calls` on a Methodology-only and a Snippet-only batch versus a mixed batch.
- `test_meta_only_ends_turn.py` — the same decision read through the `TurnAction` a real `LoopContext` receives.
- `test_meta_only_ends_turn_e2e.py` — conversation check: a meta-only batch carrying final text versus a batch that also holds `Bash`.
- `test_methodology_ends_turn.py` — `Methodology` is registered without `ends_turn=True`.
- `test_methodology_ends_turn_bug.py` — the registry value, the payload `build_messages_for_api` produces after a Methodology batch, and the any-versus-all reading of `ends_turn` over a batch.
