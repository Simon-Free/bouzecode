# multi_agent/

## Purpose
Covers `bouzecode.backend.multi_agent` — the `Agent` / `MessageAgent` /
`ListAgentTypes` tools in `multi_agent.tools`, the in-process `SubAgentManager`
(`multi_agent.subagent`, `multi_agent.manager`), terminal spawning
(`multi_agent.terminal`) and the HTTP hop to
the local server (`core.local_http`) — plus the shared task list
`bouzecode.backend.tools.task`. The approach is seams over mocks: `get_json`,
`sleep` and `now` are substituted on the module for the wait loop, `local_json` is
spied to capture what is posted, and one file stands up a real
`ThreadingHTTPServer` plus a fake 407 proxy to prove a local dispatch is never
proxied. The task tool is covered twice — units against an isolated store, and the
same behaviour through `bouzecode()` conversations driven by `MockLLM`.

## Usage
- `test_agent_tools_imports.py` — `_list_agent_types` and `get_agent_manager` resolve, the listed typologies, and how a profile's tool declaration reopens or whitelists the dispatch tools.
- `test_agent_wait_failure_is_not_a_dispatch_failure.py` — a wait that explodes still announces the created ticket and never reads as a tool error, while a dispatch that created nothing does.
- `test_agent_wait_for_child.py` — the polled URL is the real ticket route and resolves in a Flask app; the verdict is read on the runs, and the loop stops when the child hands back.
- `test_dispatch_never_proxied.py` — a local dispatch reaches the local server through a hostile proxy; a 407 accuses the proxy, a 404 the server, and a server that is down does not look like a refusal.
- `test_manager_type_guard.py` — the manager may not dispatch generic subagent types: guard, case insensitivity, refusal without spawning, and the filtered type list.
- `test_message_agent_tool.py` — `MessageAgent` registration and required params, its absence outside web IPC, the endpoint it posts to, and the resume branch carried by a spawn.
- `test_spawn_web_background.py` — `background` and `wait` semantics at spawn: default pauses, `background` hands back, and `wait` overrides it.
- `test_spawn_web_project_slug.py` — the project slug is inherited or forwarded, and a dispatch refused or unrouted by the server is reported as an error.
- `test_spawn_web_scope_warnings.py` — the server's scope warnings reach the manager without turning the dispatch into a failure.
- `test_spawn_web_ticket_timeout.py` — the dispatch call uses a generous timeout and asks the server to defer; missing keys and a missing project are handled.
- `test_subagent.py` — `SubAgentManager` and `SubAgentTask`: spawn and wait, listing, cancel, depth limit, results, `_extract_final_text`, unknown ids.
- `test_task.py` — `Task` / `TaskStatus`, the store round-trip against an isolated file, and the tool functions.
- `test_task_e2e.py` — the same task lifecycle through conversations: create, list, sequential ids, update, delete, get, and a blocker hidden once resolved.
- `test_terminal_subagent.py` — `build_terminal_command`, the result-file CLI contract, the inner-shell flag, and a spawn round trip.
