# sessions/persistence/

## Purpose

Covers the write side of session storage in `bouzecode.backend.commands.session`: the atomic
JSON helper, backup rotation, checkpoints, and the save/restore round trip through
`session_pick.restore_state`. Everything runs against real files under `tmp_path`.

## Usage

- `test_safe_write_json.py` — `_safe_write_json` retries on the Windows `PermissionError`,
  raises once the retries are exhausted, and takes the fast path when the first attempt works.
- `test_session_save.py` — `_safe_write_json` and `_rotate_backup`: file creation, atomic
  overwrite, parent directories, original kept when serialization fails, no `.tmp` left behind,
  unicode content, and `.bak` rotation including the no-file case.
- `test_checkpoint_model.py` — `_save_session_checkpoint` writes the run's model into the
  checkpoint file, from an `AgentState` carrying a `ContextState`.
- `test_compaction_log_restore.py` — the compaction log survives `_build_session_data` followed
  by `restore_state`, defaults to empty when the field is absent, and accumulates across respawns.
- `test_profile_attribution_e2e.py` — real conversations via `tests.e2e_harness.bouzecode`
  write `profile` and `run_kind` into the session, and a session lacking those fields still
  reloads through `history.json`, `save_latest` / `save_progressive` and `format_session_label`.
  Test names and docstrings are in French.
