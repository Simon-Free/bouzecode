# context_manager

## Purpose
Persistent working-memory note ("methodology") that the model writes via the `Methodology` and `Snippet` tools and that survives across turns. Cached at the system-block level so it costs cache-read price on every iteration after the first.

## Usage
Public API (re-exported from `context_manager`):
- `GCState` — dataclass with `notes: dict`. The methodology lives at `notes[METHODOLOGY_NOTE]`.
- `METHODOLOGY_NOTE` — the dict key constant ("methodology").
- `inject_notes(messages, notes)` — prepends a working-memory block to the last user message (legacy helper, not on the active dispatch path).
- `build_verbatim_audit_note(messages)` / `prepend_verbatim_audit(messages)` — list tool_results still verbatim with size + arg, used to enrich audit views.

The model-facing tools (`Methodology`, `Snippet`) live in `methodology.py` and are registered via `tools/registration.py`.

## Files
| File | Role |
|------|------|
| `state.py` | `GCState` dataclass + `METHODOLOGY_NOTE` key |
| `methodology.py` | `methodology_tool`, `snippet_tool`, cache split helpers, auto-append hooks (user msg / plan / Q&A) |
| `notes.py` | `inject_notes` legacy helper |
| `audit.py` | verbatim audit builder + arg summarizer |
