# tests/web_v2/services/sessions/

## Purpose

Covers how a session recap is assembled server-side: concatenating the recaps of a
manager's children, and turning raw `git diff` text into the ordered, grouped payload the
recap view renders.

Approach: the functions under test are pure with their dependencies injected, so the
tests pass fakes and real `git diff` fragments and assert on the returned payload. No
mocks, no LLM, no HTTP.

## Usage

- `test_aggregate_children_recaps.py` — `recap_service.aggregate_children_recaps`:
  dispatch ordering, matching a parent by key form, children with no recap kept as a
  link, per-child verdict injection, deduplication of reworked recaps (last wins), and
  the snapshots-then-git-text-then-empty fallback for diffs.
- `test_recap_diffs.py` — `recap_diffs.build_recap_payload`: one block per file with its
  flags, ordering (changes, then other, then tests), tests kept in their own section even
  when listed among the changes, and the alphabetical fallback when the recap is missing
  or empty.
- `test_recap_display_path.py` — diffs display a path relative to the repository, with
  the disposable worktree prefix stripped and separators normalized, and the assembled
  payload orders by that relative path.
