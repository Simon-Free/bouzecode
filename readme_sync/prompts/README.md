# prompts/

System prompts used by readme_sync: the regen contract, and the reader/writer navigation protocols.

---

## Module Reference

| File | Lines | Purpose |
|------|-------|---------|
| `regen_system.md` | — | The README contract, used verbatim as the system prompt when regenerating a folder README. |
| `reader.md` | — | Navigation protocol for an agent READING code: descend the README map from root to a single symbol. |
| `writer.md` | — | Maintenance protocol for an agent WRITING code: after edits the lock goes stale; run `--regen` before trusting a README. |
