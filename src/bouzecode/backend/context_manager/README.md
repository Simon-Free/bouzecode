# context_manager

## Purpose
Persistent working-memory note ("methodology") that the model writes via the `Methodology` and `Snippet` tools and that survives across turns. Cached at the system-block level so it costs cache-read price on every iteration after the first.

## Usage
Public API (re-exported from `context_manager`):
- `ContextState` — dataclass with `notes: dict`. The methodology lives at `notes[METHODOLOGY_NOTE]`.
- `METHODOLOGY_NOTE` — the dict key constant ("methodology").
- `inject_notes(messages, notes)` — prepends a working-memory block to the last user message (legacy helper, not on the active dispatch path).
- `build_verbatim_audit_note(messages)` / `prepend_verbatim_audit(messages)` — list tool_results still verbatim with size + arg, used to enrich audit views.

The model-facing tools (`Methodology`, `Snippet`) live in `methodology.py` and are registered via `tools/registration.py`.

## Files
| File | Role |
|------|------|
| `state.py` | `ContextState` dataclass + `METHODOLOGY_NOTE` key |
| `contexte_fige.py` | session-context block frozen at the session's first call; later cwd/worktree/plan changes become `[harnais]` notes, each stacked ONCE as a `## Harnais @…` block at the end of the methodology note (append-only, so in the cached prefix from the next call on; never re-sent in `<harness_notes>`) |
| `context_reset.py` | `ResetContext(reason, summary)` tool: archives the whole note to `<session>.context_<n>.md` next to the session file (persistent, chained), keeps only `## User` / `## Harnais @…` blocks plus a `## Contexte archivé` reference |
| `memoire_figee.py` | project memory frozen the same way; its changes are stacked the same way |
| `methodology.py` | `methodology_tool`, `snippet_tool`, cache split helpers, auto-append hooks (user msg / plan / Q&A) |
| `snippet_input.py` | Snippet argument leniency: implicit `ranges` (save a short source whole, refuse a long one out loud), `tool_id` repairs, dead-`tool_id` refusal |
| `snippet_resolve.py` | resolve a snippet from a file (`resolve_file_lines`, `resolve_snippet`, `resolve_snippet_symbol`) or from an inline tool_result (`find_tool_result_content`, `list_tool_result_ids`, `resolve_snippet_from_result`) |
| `note_blocks.py` | splits the note into snippet blocks / stale markers, and the dedup key |
| `compact_methodology.py` | the single trigger (cached-prefix size) and the two side-calls it chains |
| `compact_precache.py` | pre-expiration compaction: timer armed at the end of each LLM call, run before the 5-min cache TTL |
| `compact_judge.py` | side-call 1: the model judges each snippet keep-or-drop and dropped blocks leave a tombstone |
| `compact_prose.py` | side-call 2: the model re-summarises the note's prose into one `## compacted-history` block |
| `note_compactee.py` | sur refus `content_filter` : garde `## User`, snippets et blocs des deux derniers tours `### Tn`, retire les `### Tn` plus anciens ; devient l'état de la note (timeline journalisée, `allegements` +1) |
| `notes.py` | `inject_notes` legacy helper |
| `audit.py` | verbatim audit builder + arg summarizer |

An absent `ranges` is never treated as malformed input: the source is already on the wire, so a short one is saved whole (a verifiable superset) and a long one is refused with its real line count. Nothing is ever dropped silently — see `snippet_input.py` and `docs/investigations/tool_input_leniency.md`.
