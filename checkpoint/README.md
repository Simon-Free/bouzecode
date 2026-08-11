# checkpoint/

## Purpose
Automatic file snapshots with rewind. Every file a tool is about to modify is copied to a per-session backup directory, and a snapshot groups those copies so the working tree can be restored to an earlier point of the session.

## Usage
- `types.py` — `FileBackup`, `Snapshot`, `MAX_SNAPSHOTS` — dataclasses with `to_dict()`/`from_dict()` serialization
- `store.py` — `track_file_edit()`, `make_snapshot()`, `list_snapshots()`, `get_snapshot()`, `rewind_files()`, `files_changed_since()`, `delete_session_checkpoints()`, `cleanup_old_sessions()`, `reset_file_versions()` — backups are hashed-path files under a per-session directory, metadata in `snapshots.json`
- `hooks.py` — `install_hooks()`, `set_session()`, `get_tracked_edits()`, `reset_tracked()` — wraps the Write/Edit/NotebookEdit tools so `_backup_before_write()` runs before each modification
- `__init__.py` re-exports the public surface
