# context_viewer

## Purpose
Reconstructs, for every LLM call in a bouzecode session, the full list of
context objects actually sent — system prompt, notes, every user/assistant/tool
message — with char-based token estimates (chars / 3.5) and a cached/new-cache/
fresh badge derived from the replayed `_cache_breakpoint` positions.

## Usage
```python
from web.context_viewer import render_context_viewer, build_turn_breakdowns
render_context_viewer(session_json_path)   # standalone HTML page
build_turn_breakdowns(session_json_path)   # inline session-page stats bar
```

Files:
- `builder.py` — reads the session JSON, replays GC and breakpoint logic, emits per-call data
- `items.py` — token estimation, tool-call briefs, message-to-item conversion
- `__init__.py` — public API and HTML page template
