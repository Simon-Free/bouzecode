# tests/cli/

## Purpose
Covers the command line's exit-code and output contract. Approach: the real
`python -m readme_sync` run as a subprocess over a temporary tree, through the
`run_cli` and `mini_tree` fixtures of the parent `conftest.py`.

## Usage
- `test_check_exit_codes.py` — `--check` exits 1 while a folder is stale and 0 once every folder is fresh; `--list-stale` prints bare paths with no decoration.
