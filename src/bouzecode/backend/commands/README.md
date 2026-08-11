# commands/

## Purpose
All `/slash` commands for the REPL, plus the dispatcher that maps command names to handlers and the readline setup with tab-completion.

## Usage
- `dispatcher.py` — `COMMANDS` dict, `handle_slash()`, `_CMD_META`, `_REPL_SENTINELS`. Importing a handler here does NOT wire it: a command absent from `COMMANDS` answers "Unknown command" however complete its module is (`/telegram`, then `/worker`, `/ssj`, `/image`). `COMMANDS` and `_CMD_META` must hold the same keys — otherwise a command is dispatchable and invisible to `/help`.
- `readline_setup.py` — `setup_readline()` (history + tab-completion)
- Per-command modules export one or more `cmd_<name>(args, state, config)` handlers that return `True` (handled), a sentinel tuple (REPL-dispatched follow-up), or a `SkillDef` tuple.
- `__init__.py` re-exports the public surface: `COMMANDS`, `handle_slash`, `setup_readline`, `ask_permission_interactive`, `save_latest`, `save_progressive`, `_build_session_data`, `_proactive_watcher_loop`, `_tg_send`, `_print_background_notifications`.
