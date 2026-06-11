# checkpoint/

The checkpoint package implements conversation snapshots and file-level undo: save state at key moments, rewind to any earlier checkpoint.

---

## Entry Points

| Function | File | Description |
|----------|------|-------------|
| `make_snapshot()` | `snapshot.py` | Create a checkpoint (messages + file backups) |
| `rewind()` | `rewind.py` | Restore conversation & files to a previous checkpoint |
| `list_snapshots()` | `snapshot.py` | List all checkpoints for a session |
| `delete_session_checkpoints()` | `store.py` | Remove all checkpoint data for a session |
| `install_hooks()` | `hooks.py` | Intercept Write/Edit to back up files before modification |

---

## Main Call Graph — `make_snapshot()`

```
make_snapshot(session_id, state, config)
 │
 ├── hooks.get_tracked_edits()              [hooks.py]
 │    → dict of file_path → backup_filename
 │
 ├── store.save_snapshot(session_id, data)   [store.py]
 │    ├── messages (serialized)
 │    ├── methodology note
 │    └── file backups manifest
 │
 └── hooks.reset_tracked()                   [hooks.py]
```

---

## Main Call Graph — `rewind()`

```
rewind(session_id, snapshot_id, state, config)
 │
 ├── store.load_snapshot(session_id, id)     [store.py]
 │    → snapshot data (messages, methodology, file manifest)
 │
 ├── [restore files]
 │    └── store.restore_file_backup(session_id, backup_name, target_path)
 │         → overwrites current file with backed-up version
 │
 ├── state.messages = snapshot.messages
 │
 └── [cleanup newer snapshots]
      └── store.delete_snapshots_after(session_id, id)
```

---

## Hook Flow — file backup on Write/Edit

```
install_hooks()                               [hooks.py]
 │
 └── wraps Write / Edit / NotebookEdit tools
      │
      └── _backup_before_write(file_path)
           ├── [skip if already tracked this interval]
           └── store.track_file_edit(session_id, file_path)
                → copies current file to checkpoint storage
```

---

## Module Reference

| File | Description |
|------|-------------|
| `__init__.py` | Public API re-exports (`make_snapshot`, `rewind`, `list_snapshots`, etc.) |
| `snapshot.py` | Snapshot creation and listing logic |
| `rewind.py` | Rewind/restore logic — rolls back messages and files |
| `store.py` | Storage layer — read/write checkpoint data to disk |
| `hooks.py` | Tool hooks — intercepts Write/Edit/NotebookEdit for pre-modification backups |

---

## External Dependencies

| Dependency | Usage |
|------------|-------|
| `tool_registry.get_tool()` | Hook installation — wraps tool functions |
| `agent.state` | Access to conversation messages during snapshot/rewind |
| `/checkpoint` CLI command | User-facing command in `commands/checkpoint_cmd.py` |

---

## Storage Layout

Checkpoints are stored per-session under the bouzecode data directory:

```
~/.bouzecode/checkpoints/<session_id>/
 ├── manifest.json          # ordered list of snapshots
 ├── snap_001.json          # snapshot data (messages, methodology)
 ├── snap_002.json
 └── backups/
      ├── <hash>_original   # file content before first edit
      └── ...
```
