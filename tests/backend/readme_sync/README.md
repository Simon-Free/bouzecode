# tests/backend/readme_sync/

## Purpose
Covers the naming layer of the `readme_sync` package: which filename counts as a
folder map, which lock sidecar follows it, and how a folder carrying a map but no
lock is classified. Real folders are built in `tmp_path` and passed to the actual
`hashing.classify` / `hashing.scan`; an autouse fixture restores the active naming
after each test.

## Usage
- `test_folder_map_naming.py` — `naming.resolve_naming` defaults to `README.md`, `naming.lock_name_for` derives the lock sidecar, and precedence runs explicit override > environment (`naming.ENV_DOC_NAME`) > `[tool.readme_sync]` in `pyproject.toml`; a documented folder is not `FolderState.MISSING` under the matching name, a map without its lock is `FolderState.UNLOCKED` and not `needs_attention`, and `scan` of such a tree flags nothing.
