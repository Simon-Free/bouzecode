# checkpoint/

## Purpose
Tests of `bouzecode.backend.checkpoint` (types, store, hooks) and of the two things
built on it: the `GetDiff` tool and `commands.session.revert_cmd.cmd_revert`. The
storage layer is pinned at unit level against a temporary checkpoint root; what a user
sees — review a diff, undo a request — is driven as a real `bouzecode()` conversation.

## Usage
- `test_checkpoint.py` — snapshot numbering, first-write-wins file backups, version bookkeeping, rollback, JSON round-trips, and the edit hooks.
- `test_checkpoint_store.py` — `checkpoint.store` against a redirected root: an oversized file is skipped and logged to stderr, a normal file is backed up, a failing backup is logged.
- `test_getdiff_e2e.py` — a conversation Writes and Edits files, calls `GetDiff` (whole session, filtered by path, no changes), then the real `cmd_revert` is run the way the REPL does, on snapshots the conversation itself produced.
- `test_getdiff_revert.py` — the bookkeeping half of `/revert`: message history, turn counter and the four token totals rewound to the checkpoint, plus the no-session and no-checkpoint refusals.
