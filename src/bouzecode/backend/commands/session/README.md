# session/

## Purpose
Session persistence: save, load, checkpoint, revert.

## Usage
- `session.py` — `cmd_save`, `cmd_where`, `save_latest`, `save_progressive`, `_build_session_data`, `_safe_write_json`, `_rotate_backup`, `_save_session_checkpoint`
- `session_load.py` — `cmd_load`, `cmd_resume`
- `checkpoint_cmd.py` — `cmd_checkpoint` (aliased as `/rewind`)
- `revert_cmd.py` — `cmd_revert`
