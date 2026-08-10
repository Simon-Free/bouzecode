# Writer — AGENTS.md maintenance protocol

You are editing code in a repository whose folder `AGENTS.md` files form a
synchronized map (maintained by `readme_sync`). Keeping that map fresh is part of
your job — a stale map costs every future reader. `README.md` files are 100% human
and are never written by this system.

## What happens when you edit code

- Every folder has a sidecar `.agents.lock` (JSON) recording the SHA-256 of each of
  its code files. A `PostToolUse` hook runs after each `Write`/`Edit`.
- When you edit a **code file**, the hook flips that folder's lock to
  `"stale": true` (it creates the lock if missing). Editing the `AGENTS.md` itself,
  or a non-code file, is a no-op.
- A `"stale": true` lock means: **the AGENTS.md no longer matches the code.**

## Rules

1. **Never trust an AGENTS.md whose lock says `"stale": true`.** Its `## Module Reference`
   and `## Subfolders` tables may be out of date.
2. **After changing code, refresh the docs.** Run `readme_sync --check` to see the
   map of stale/missing folders, then `readme_sync --regen <folder>` to regenerate
   the affected AGENTS.md. Regen is a single LLM call per folder; it rewrites the
   AGENTS.md, resets the lock to `"stale": false`, and mechanically propagates the
   folder's one-line purpose up into its parents' `## Subfolders` tables, all the way
   to root.
3. **Only stale/missing folders are regenerated.** `readme_sync --regen` (no path)
   regenerates exactly the flagged folders — fresh folders are never touched, so no
   wasted LLM calls.
4. **Do not hand-edit the `## Subfolders` tables** — they are derived mechanically
   from children. Edit a child's one-line purpose (right under its H1 title); regen
   propagates it upward.

## Folder states (`readme_sync --check`)

- `FRESH` — AGENTS.md matches code.
- `STALE` — code changed / a file was added or removed / the hook flagged it.
- `MISSING` — a code folder with no AGENTS.md.
- `ORPHAN` — an AGENTS.md with no code left.
