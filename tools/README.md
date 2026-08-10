# tools/

## Purpose
Built-in agent tools (Read, Write, Edit, Bash, Grep, Glob, WebFetch, etc.), their JSON schemas, user-interaction helpers, and the registration wiring into `tool_registry`.

## Usage
- `schemas.py` — `TOOL_SCHEMAS` (list of dicts)
- `state.py` — `_track_read`, `_stale_edit_warning`, `_tg_thread_local`, `_is_in_tg_turn`, `clear_file_state`
- `interaction.py` — `_ask_user_question`, `ask_input_interactive`, `drain_pending_questions`, `_sleeptimer`
- `plan_mode.py` — plan-mode tool gating
- `registration.py` — `_register_builtins()`, `execute_tool()`
- `__init__.py` re-exports the public surface

## Subfolders
| Folder | Description |
|--------|-------------|
| `ops/` | File/shell/web/notebook operations (`_read`, `_write`, `_edit`, `_bash`, `_glob`, `_grep`, `_webfetch`, `_notebook_edit`, `_get_diagnostics`) |
