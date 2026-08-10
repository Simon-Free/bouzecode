# tools/ops/

## Purpose
Concrete implementations of the built-in agent tools (file I/O, shell, web, notebooks, diagnostics).

## Usage
- `file_ops.py` — `_read`, `_write`, `_edit`, `generate_unified_diff`, `maybe_truncate_diff`
- `edit_match.py` — why an `Edit` missed: `describe_missing_old_string` (line-level diff marking diverging lines with `≠`), `find_uniform_reindent` + `reindent_block` (the ONE tolerated repair, under four cumulative guards)
- `edit_context.py` — post-edit enrichment: `build_edit_context`, `find_enclosing_symbol`
- `read_params.py` — `normalize_read_params`: converts Snippet's 1-indexed `ranges` / `start_line` into Read's 0-indexed `offset`+`limit`, refuses multi-range and `command=`
- `shell_search.py` — `_bash`, `bash_handler`, `_build_popen_command`, `_kill_proc_tree`, `_is_safe_bash` (re-exports the search helpers below)
- `shell_command_rewrite.py` — `unwrap_nested_powershell`, `spill_inline_python`: the two pre-execution rewrites (see below)
- `shell_env.py` — `_get_env_with_user_vars`, `_merge_user_env`, `_powershell_exe`: the environment a command runs in
- `grep_glob.py` — `_glob`, `_grep`, `_has_rg`, `_build_grep_summary`
- `glob_cap.py` — `cap_glob_matches`, `GLOB_CAP`: a Glob result over the cap prints its first `GLOB_CAP` paths plus a directory rollup of the rest. A cap, never a refusal
- `bash_bg.py` — `start_background`, `bash_output`
- `web_ops.py` — `_webfetch`, `_websearch`
- `notebook_diagnostics.py` — `_notebook_edit`, `_get_diagnostics`, `_detect_language`, `_run_quietly`

### Why a command may not run verbatim
- A command that is itself `powershell -Command "..."` is **unwrapped**: Bash already runs
  PowerShell, and the extra shell interpolates the body's variables away before the inner
  one sees them. Wrappers carrying `-ExecutionPolicy`, `-File`, or `pwsh` are left alone —
  decision boundary in `shell_command_rewrite.unwrap_nested_powershell`.
- `python -c "<code>"` is **spilled** to a `temp_*.py` scratch file which is then run; the
  tool result says where. It is refused only when the code cannot be unquoted losslessly.
