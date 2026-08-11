# memory/

## Purpose
Persistent, file-based memory across conversations. Each memory is a markdown file with frontmatter, stored in a user scope (shared across projects) or a project scope; a `MEMORY.md` index is rebuilt automatically and injected into the system prompt.

## Usage
- `types.py` — `MEMORY_TYPES`, `MEMORY_TYPE_DESCRIPTIONS`, `MEMORY_SYSTEM_PROMPT`, `WHAT_NOT_TO_SAVE`, `MEMORY_FORMAT_EXAMPLE` — the four-type taxonomy and the guidance text injected into the prompt
- `store.py` — `MemoryEntry`, `save_memory()`, `delete_memory()`, `load_entries()`, `load_index()`, `search_memory()`, `get_index_content()`, `parse_frontmatter()`, `check_conflict()`, `touch_last_used()`, `get_memory_dir()` — CRUD over the scoped directories, with `_rewrite_index()` keeping `MEMORY.md` in sync
- `scan.py` — `MemoryHeader`, `scan_memory_dir()`, `scan_all_memories()`, `format_memory_manifest()`, `memory_age_days()`, `memory_age_str()`, `memory_freshness_text()` — newest-first listing with human-readable age and a staleness caveat
- `context.py` — `get_memory_context()`, `find_relevant_memories()`, `truncate_index_content()` — builds the prompt block within line and byte caps; keyword filtering with an optional model-assisted selection pass
- `consolidator.py` — `consolidate_session()` — extracts up to a few durable insights from a finished session and saves them at reduced confidence, skipping short sessions and never overwriting a stronger entry
- `tools.py` — registers the `MemorySave`, `MemoryDelete`, `MemorySearch` and `MemoryList` tools
- `__init__.py` re-exports the public surface
