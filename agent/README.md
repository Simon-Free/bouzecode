# agent/

## Purpose
Agent turn loop: stream LLM → execute tools → append results → loop until TurnDone. Handles permission checks, DAG-based parallel tool execution, and event emission.

## Usage
- `state.py` — `AgentState` dataclass + event types (`TextChunk`, `ThinkingChunk`, `ToolStart`, `ToolEnd`, `TurnDone`, `PermissionRequest`, `CheckpointReady`)
- `loop.py` — `run(user_input, state, config, system_prompt)` generator; yields events
- `dag.py` — build dependency levels, execute tools in parallel via `ThreadPoolExecutor`
- `permissions.py` — `_check_permission()`, `_permission_desc()`, `_propagate_denials()`
