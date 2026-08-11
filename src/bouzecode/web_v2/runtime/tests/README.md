# runtime/tests/

## Purpose
Covers the runtime paths whose failure is silent or fatal to the server: the IPC
state write, listing and loading agents from a damaged agents directory, the
working-directory guard on resume, the deferred store, and the warm-pool policy.
Approach: unit tests over `tmp_path` with `AGENTS_DIR` repointed at it — no
process spawn, no network, no model. One test is Windows-only.

## Usage
- `test_ipc_state_lock.py` — `write_state` does not raise while `state.json` is held open by a reader, and round-trips status and turn.
- `test_runner_load_corrupt.py` — `load_agent` returns `None` on invalid JSON and on a missing file.
- `test_runner_sidecar_skip.py` — `_list_agents_uncached` skips the `.pending.json` / `.deferred.json` sidecars instead of parsing them.
- `test_runner_safe_cwd_dead_worktree.py` — `_is_dead_worktree` and `_safe_cwd` reject a worktree directory that lost its `.git`, keep a live one and keep a non-git project directory.
- `test_runner_list_cache_invalidation.py` — `_save` invalidates the `list_agents` cache so a new agent is visible without waiting for the TTL.
- `test_deferred.py` — save / load / delete round trip next to a session, `DeferredChecks` fields, and (Windows) `_run_deferred_check` executing PowerShell syntax.
- `test_warmpool.py` — `decide_evictions` under the inactivity TTL, LRU pressure limited to terminated agents, immunity of an active agent or of a parent with an active child, and non-warm nodes never evicted.
