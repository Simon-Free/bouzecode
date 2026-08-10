# core/

## Purpose
Core REPL commands and setup.

## Usage
- `basic.py` — `cmd_help`, `cmd_clear`, `cmd_model`, `cmd_config`, `cmd_exit`, `cmd_tools`, `ask_permission_interactive`
- `settings.py` — `cmd_verbose`, `cmd_thinking`, `cmd_permissions`, `cmd_cwd`
- `plan_cmd.py` — `cmd_plan`
- `readline_setup.py` — `setup_readline()` (history + tab-completion). Not re-exported by `__init__` to avoid a circular import with the dispatcher.
