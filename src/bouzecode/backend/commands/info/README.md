# info/

## Purpose
Read-only information and diagnostics commands.

## Usage
- `info.py` — `cmd_info`, `cmd_history`, `cmd_context`, `cmd_cost`, `cmd_timing`
- `diagnostics.py` — `cmd_doctor` (session summary + environment health checks)
- `runtime_checks.py` — `ripgrep_status`, `tool_registry_status`: the two checks
  `/doctor` renders, as `(level, message)` pairs so they can be asserted directly
