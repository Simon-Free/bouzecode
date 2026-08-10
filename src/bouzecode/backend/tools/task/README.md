# Task Management Tools

Built-in task tracking system for bouzecode agents — lets the LLM create, update, query, and list work items within a session.

## Architecture

```
task/
├── types.py    — TaskStatus enum + Task dataclass (serialization, display)
├── store.py    — Thread-safe in-memory store with JSON file persistence
├── tools.py    — Tool definitions & registration (JSON schemas, handlers)
└── __init__.py — Package init, re-exports public API
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Task** | Dataclass with id, subject, description, status, owner, metadata, and dependency edges (blocks/blocked_by). |
| **TaskStatus** | Enum: `pending`, `in_progress`, `completed`, `cancelled`, `deleted`. |
| **Persistence** | Tasks are stored in-memory and synced to a JSON file (`tasks.json`) in the session directory. Thread-safe via a module-level lock. |
| **IDs** | Short sequential numeric strings (e.g. "1", "2", "3"). |

## Exposed Tools

| Tool | Purpose |
|------|---------|
| `TaskCreate` | Create a new task with subject, description, optional active_form and metadata. |
| `TaskUpdate` | Update status, subject, description, owner, dependency edges, or metadata of an existing task. |
| `TaskGet` | Retrieve full details of a single task by ID. |
| `TaskList` | List all non-deleted tasks with id, subject, status, owner, and pending blockers. |

## Usage

Tools are auto-registered at import time via `_register()` in `tools.py`. No manual setup needed — importing the `task` package is sufficient.

## Thread Safety

All store operations (`create_task`, `update_task`, `delete_task`, etc.) are protected by a `threading.Lock`. The store supports `clear_all_tasks()` and `reload_from_disk()` helpers for test isolation.
