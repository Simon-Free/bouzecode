# plan_mode/ipc/

## Purpose
Plan validation as seen from the IPC state file the web UI watches: `_write_plan`
parking an agent, `bouzecode.ui.repl._persist_pause_and_exit` writing the pause
status, and the agent categorisation that fills the "awaiting" column. The two unit
files cover the cases a conversation cannot reach — the terminal prompt reads real
stdin, and categorisation is a pure function of an already-running agent's status —
so they call the functions directly against a temporary IPC directory; the `_e2e`
file plays `bouzecode()` conversations with `MockLLM` and reads the JSON left behind.

## Usage
- `test_plan_validation_ipc.py` — the terminal path asks the user and writes no IPC state, rejects a negative answer, and `_agent_category` files an agent awaiting a plan or a question under "awaiting".
- `test_plan_validation_not_overwritten.py` — `_persist_pause_and_exit` writes `awaiting_plan_validation` for a plan pause and `awaiting_input` for a normal question.
- `test_write_plan_ipc_e2e.py` — `WritePlan` writes `plan.md` beside the agent, appends rather than overwrites, rejects empty content, and parks the agent until the user approves.
