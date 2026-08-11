# multi_agent/

## Purpose
Spawning and supervision of sub-agents. An agent type supplies a system prompt, model and tool allowlist; the manager runs tasks synchronously or in the background, optionally inside a throwaway git worktree.

## Usage
- `definitions.py` — `AgentDefinition`, `load_agent_definitions()`, `get_agent_definition()` — built-in agent types plus custom ones parsed from `.md` files with frontmatter by `_parse_agent_md()`
- `task.py` — `SubAgentTask` — one running task (status, result, message queue, future); `_create_worktree()` / `_remove_worktree()` for isolation, `_agent_run()` to drive the loop, `_extract_final_text()` for the answer
- `manager.py` — `SubAgentManager` — `spawn()`, `wait()`, `get_result()`, `list_tasks()`, `send_message()`, `cancel()`, `shutdown()`, bounded by `max_concurrent` and a nesting `max_depth`
- `tools.py` — registers `Agent`, `SendMessage`, `CheckAgentResult`, `ListAgentTasks` and `ListAgentTypes`; `get_agent_manager()` returns the shared manager
- `subagent.py` re-exports the three modules under one name
- `__init__.py` re-exports the public surface
