# tests/backend/core/

## Purpose
Covers two helpers of `bouzecode.backend.core`: turning a plugin source (browser URL,
SSH remote, local git folder) into install coordinates, and the worktree contract the
system prompt carries when an agent runs in an isolated checkout. No network and no
`pip install` — resolution reads a real `git init` repo created in `tmp_path`.

## Usage
- `test_gitlab_resolve.py` — `_parse_gitlab_url` (plain, `/-/tree/<ref>/<subpath>`, `.git` suffix), `resolve_input` (SSH normalized to HTTPS, local path deduced from its remote, invalid input raising `SourceError`), and `plugin_install_target` deriving the pip name and `git+https` source.
- `test_worktree_contract_system.py` — `build_system_prompt_parts` adds the worktree contract to the volatile half only when `BOUZECODE_WORKTREE_ROOT` is set and non-empty.
