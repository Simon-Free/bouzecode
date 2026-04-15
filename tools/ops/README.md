# tools/ops/

## Purpose
Concrete implementations of the built-in agent tools (file I/O, shell, web, notebooks, diagnostics).

## Usage
- `file_ops.py` — `_read`, `_write`, `_edit`, `generate_unified_diff`, `maybe_truncate_diff`
- `shell_search.py` — `_bash`, `_kill_proc_tree`, `_is_safe_bash`, `_glob`, `_grep`, `_has_rg`
- `web_ops.py` — `_webfetch`, `_websearch`
- `notebook_diagnostics.py` — `_notebook_edit`, `_get_diagnostics`, `_detect_language`, `_run_quietly`
