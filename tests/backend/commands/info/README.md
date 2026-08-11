# commands/info/

## Purpose
Tests of `bouzecode.backend.commands.info` — the informational commands. Handlers are
called directly; the only environment touched is a temporary dir and the tool registry.

## Usage
- `test_cmd_history_import.py` — `info.info.cmd_history` imports and runs (its replay import resolves).
- `test_doctor_runtime_checks.py` — `info.runtime_checks.ripgrep_status`, `tool_registry_status` and `ESSENTIAL_TOOLS`: ripgrep reported either way, a healthy registry counts its tools, a disabled essential tool is reported, and `info.diagnostics.cmd_doctor` renders both checks.
