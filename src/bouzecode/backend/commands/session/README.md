# session/

## Purpose
Session persistence: save, load, checkpoint, revert.

## Usage
- `session.py` — `cmd_save`, `cmd_where`, `save_latest`, `save_progressive`, `_build_session_data`, `_safe_write_json`, `_rotate_backup`, `_save_session_checkpoint`
- `session_load.py` — `cmd_load`
- `session_resume.py` — `cmd_resume` (interactive picker of recent sessions, paged)
- `session_pick.py` — shared helpers: `restore_state`, `format_session_label`, `collect_recent_sessions`
- `checkpoint_cmd.py` — `cmd_checkpoint` (aliased as `/rewind`)
- `revert_cmd.py` — `cmd_revert`
