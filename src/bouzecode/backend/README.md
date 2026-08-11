# backend/

## Purpose
The engine, split into one subpackage per concern. The package itself carries no module-level code — everything is reached through its children.

## Usage
- `__init__.py` is an empty package marker; there is no backend-level module to import from.

## Subfolders
| Folder | Description |
|--------|-------------|
| `agent/` | The turn loop: stream the LLM, execute tools, append results, loop until done; provider adapters and permission checks |
| `checkpoint/` | Conversation snapshots and file-level undo — save state at key moments, rewind to an earlier point |
| `chrome_devtools/` | Minimal MCP client that launches a browser devtools server and registers its tools |
| `commands/` | All `/slash` commands for the REPL, the name-to-handler dispatcher, and readline setup |
| `context_manager/` | The persistent working-memory note written via `Methodology` and `Snippet`, cached across turns |
| `core/` | Config, tool registry, system-prompt assembly, extra source dirs, payload views |
| `multi_agent/` | Sub-agent spawning and lifecycle (thread, terminal tab, web ticket) and the `Agent` tool family |
| `plugin/` | Install, enable and load plugin packages contributing tools, hooks and skills |
| `profiles/` | Agent profiles in YAML — model, tools, skills, prompt fragments — with loading, merging, discovery and a remote catalog |
| `tests/` | Backend unit tests |
| `tools/` | Built-in agent tools (Read, Write, Edit, Bash, Grep, Glob, WebFetch…), their schemas and registration |
| `xml_tool_protocol/` | Tool calls encoded as XML inside the text stream, for proxies that mishandle native tool-use blocks |
