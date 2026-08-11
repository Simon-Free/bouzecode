# tests/web_v2/services/work/

## Purpose

Covers two reconciliation behaviours of `bouzecode.web_v2.services.work`: turning a dead
run into a crashed ticket, and giving an agent a valid working directory again before it
is respawned.

Approach: the real services driven directly, with a real git repository for the worktree
paths and plain injected fakes for the rest. No `mock.patch`, no LLM, no HTTP.

## Usage

- `test_reconcile_api_crash.py` — a run whose agent died with `close_reason="api_error"`,
  without being completed and without a verdict, is an immediate crash:
  `_reconcile_api_crash` marks the ticket crashed, and leaves graceful closures alone.
- `test_rehome_agent_cwd.py` — `rehome_agent_cwd` on an agent whose worktree was cleaned
  up after a merge: it either provisions a fresh worktree or falls back to the repository
  root, instead of spawning into a directory that no longer exists.
