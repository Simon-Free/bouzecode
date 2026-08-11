# tests/feature/

## Purpose
Covers readme_sync from the user's side: staleness detection, the edit hook, map
propagation to parent folders, and regeneration. Approach: the real
`python -m readme_sync` and `python -m readme_sync.hook` run as subprocesses over
a temporary tree (`mini_tree` and `run_cli` from the parent `conftest.py`), with
propagation and contract checks called in process. Tests that hit a model are
marked `@pytest.mark.llm` and skip when no API credentials are set.

## Usage
- `test_detection.py` — `--check` and `--list-stale` on a virgin, fresh, edited, extended, truncated and emptied tree, plus exclusion of virtual environments (by `pyvenv.cfg`) and of gitignored directories from `iter_code_folders`.
- `test_javascript_folders.py` — a folder of hand-written `.js` is classified like a folder of `.py` (missing without a map, fresh with one, stale once a script is edited), and a vendored bundle is neither walked nor counted.
- `test_hook.py` — the hook marks a folder's lock stale on a code edit, no-ops on the map file and on non-code files, and creates the lock when it is missing.
- `test_map.py` — model-free: a child's purpose reaches its parent's Subfolders row, no map links to a missing file, every code folder is reachable from the root map, and the root lists all top-level packages.
- `test_contract.py` — `REQUIRED_SECTIONS` declares the guaranteed sections, and a real in-repo map passes `validate()`.
- `test_regen.py` — with a model: `regen_folder` writes a contract-valid map naming the real symbols, clears the stale flag, reflects a renamed function, and `--regen` calls the model only for stale folders.
- `test_end_to_end.py` — with a model: the whole flow, fresh tree, rename, hook, `--check` failing, `--regen`, `--check` passing.
- `test_system_verification.py` — scan exclusions, a plausible folder count on the real repository, bootstrap guards (folder cap, worktree, env switch), the navigation section injected into the system prompt, and with a model a generated tree whose root map leads to a leaf symbol that `find_symbol` resolves in the file.
