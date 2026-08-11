# regression/

## Purpose

Locks on the repository itself rather than on a feature. Three families: the code still starts
and every import resolves (`smoke/`), modules stay where they were put and the packaging keeps
declaring what it must (`structure/`), and features that were taken out do not come back
(`removed/`). None of them needs an LLM or a conversation.

## Usage

This package holds no test module of its own — only an empty `__init__.py` so the three
subpackages import without shadowing each other. The tests live in the subfolders below.

## Subfolders

| Folder | Description |
|--------|-------------|
| `smoke/` | The package imports, compiles, runs `python -m`, and its version matches the metadata. |
| `structure/` | Where modules live, what the packaging declares, and cross-file conventions. |
| `removed/` | A deleted module stays unimportable and unregistered, and its former callers still import. |
