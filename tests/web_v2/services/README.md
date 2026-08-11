# tests/web_v2/services/

## Purpose

Container package for the unit tests of `bouzecode.web_v2.services`. It mirrors the
layout of the production package, one test folder per service package, so a test lives
at the same path as the code it covers.

It holds no test of its own: `__init__.py` is empty and exists only to keep the
`__init__.py` chain from `tests/` unbroken, which is what gives every test module a
fully-qualified, collision-free name under `--import-mode=importlib`.

## Usage

No `.py` file in this folder carries behaviour.

## Subfolders

| Folder | Description |
|--------|-------------|
| `sessions/` | Recap assembly: aggregating children recaps, ordering diffs, relative display paths. |
| `work/` | Ticket-side reconciliation: routing an API-error run to crash, re-homing an agent whose worktree is gone. |
