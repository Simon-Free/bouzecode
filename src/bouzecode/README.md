# bouzecode/

## Purpose
Package root. Holds the version, the `main()` entry point (which hands off to the REPL CLI), and lazy attribute re-exports so importers can do `from bouzecode import X` without pulling the whole engine at import time. All real code lives in the subpackages.

## Usage
- `__init__.py` — `VERSION`, `main()` (delegates to `ui.cli.main`), and a module-level `__getattr__` that resolves `COMMANDS` / `handle_slash` from the command dispatcher plus a few compatibility names on demand
- `__main__.py` — makes `python -m bouzecode` call `main()`

## Subfolders
| Folder | Description |
|--------|-------------|
| `backend/` | The engine: turn loop, tools, registry, prompts, profiles, plugins, sub-agents |
| `ui/` | Interactive REPL, terminal rendering, spinner, tool output formatting |
| `web_v2/` | Web UI to drive a fleet of agents, rendered server-side from structured JSON |
