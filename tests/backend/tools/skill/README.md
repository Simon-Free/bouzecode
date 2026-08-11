# tools/skill/

## Purpose

Documentation guard over the builtin skill prompts exported by
`bouzecode.backend.tools.skill.builtin`. It reads the prompt constant itself — the
source of truth — and asserts the rules it must still carry, so a section cannot
disappear silently.

## Usage

- `test_fast_testing_doc.py` — `builtin._FAST_TESTING_PROMPT` keeps the
  derived-fixtures rule, names a real API value, cites the before/after production
  filter example, and points visual checks at a real browser.
