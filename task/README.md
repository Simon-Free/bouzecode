# task/

## Purpose
A lightweight task list the model can drive through tools: tasks carry a status, an owner and blocking relationships, and live in a thread-safe in-memory store persisted to a JSON file.

## Usage
- `types.py` — `Task`, `TaskStatus`, `VALID_STATUSES` — dataclass with `to_dict()`/`from_dict()`, plus `status_icon()` and `one_line()` for display
- `store.py` — `create_task()`, `get_task()`, `list_tasks()`, `update_task()`, `delete_task()`, `clear_all_tasks()`, `reload_from_disk()` — lock-guarded dict flushed to `tasks.json` on every mutation; `update_task()` also maintains the `blocks`/`blocked_by` links
- `tools.py` — registers the `TaskCreate`, `TaskUpdate`, `TaskGet` and `TaskList` tools with their JSON schemas
- `__init__.py` re-exports the public surface
