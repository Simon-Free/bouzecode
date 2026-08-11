# multi_agent/

## Purpose
Sub-agent spawning and lifecycle: create a task, apply its profile, run it (in a thread, in a new terminal tab, or as a ticket on the local web server), and collect its result. Also registers the model-facing `Agent` tool family.

## Usage
- `manager.py` — `SubAgentManager`: `create_task`, `spawn`, `wait`, `get_result`, `list_tasks`, `send_message`, `cancel`, `shutdown`. Enforces `max_concurrent` and `max_depth`, resolves and merges the requested profiles into the child's system prompt, and optionally isolates the child in a git worktree
- `task.py` — `SubAgentTask` dataclass (status, result, thread, worktree) plus the worktree helpers `_git_root`, `_create_worktree`, `_remove_worktree`, and `_agent_run` / `_extract_final_text` used to drive one child turn loop
- `tools.py` — registers `Agent`, `MessageAgent`, `SendMessage`, `CheckAgentResult`, `ListAgentTasks`, `ListAgentTypes` and `Fleet` into the tool registry; `get_agent_manager()` returns the per-process manager. Holds the three spawn backends (in-process thread, terminal tab, web ticket) and the ticket polling that waits for a child's verdict
- `terminal.py` — `detect_terminal_app`, `build_terminal_command`, `spawn_in_terminal`: opens a child agent in a new terminal tab
- `plugin_resolver.py` — `ensure_plugins(requirements)`: installs and enables a profile's required plugins at launch and returns the tool names they contribute
- `subagent.py` — flat re-export of `task` and `manager`, including the private worktree helpers, for call sites that import them from one place
- `__init__.py` re-exports `SubAgentTask` and `SubAgentManager`
