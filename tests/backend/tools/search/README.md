# tools/search/

## Purpose

Covers the shell and search tools: `bouzecode.backend.tools.ops.shell_search` (the
`Bash`, `Grep` and `Glob` handlers, command building, environment merging, output
cleanup) and `tools.ops.bash_bg` (background execution and `BashOutput`).

Unit files call `_bash`, `_grep`, `_glob` and their helpers directly, over a temporary
git project when gitignore behaviour matters. The `_e2e` files run whole conversations
through the `bouzecode()` harness with `MockLLM` and read the tool results back.

## Usage

- `test_bash_background.py` — `_build_popen_command` spills a long command to a `.ps1`
  on win32 so no command-length limit applies, and background Bash plus `bash_output`
  return the process output. Platform-gated.
- `test_clixml_strip.py` — `_strip_clixml` removes PowerShell progress noise from stderr
  while leaving real errors intact.
- `test_env_user_vars_merge.py` — `_merge_user_env` merges registry variables
  case-insensitively, so the registry never shadows the in-process `PATH`, and never
  creates a case-conflicting duplicate key.
- `test_gitignore_grep_glob.py` — `ignore_gitignore` and `include_patterns` on `_grep`
  and `_glob`, driven with a fake subprocess result.
- `test_grep_summary.py` — `_build_grep_summary`, `_extract_precise_patterns` and the
  `_GREP_BUDGET` cap: an overflowing grep answers with match counts, a directory
  breakdown and refinement suggestions instead of raw lines.
- `test_search_e2e.py` — the same three behaviours in conversation: inline `python -c`
  is spilled to a temp script rather than refused, Grep and Glob honour gitignore and
  its overrides, and an overflowing Grep returns the structured summary.
- `test_shell_nesting_spill_e2e.py` — a nested `powershell -Command` wrapper is unwrapped
  without eating its own body's variables, while a deliberate wrapper (execution policy,
  `pwsh`) is kept; inline Python is spilled and reported, and an unquoted one is refused.
