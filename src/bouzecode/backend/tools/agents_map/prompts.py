# [desc] The two generation system prompts: the SYMBOLS.md contract and the root AGENTS.md contract. [/desc]
from __future__ import annotations

CONTRACT_VERSION = 1

SYMBOLS_SYSTEM_PROMPT = """\
You produce the `SYMBOLS.md` of ONE code folder: a symbol map an agent reads
INSTEAD of opening the files. Output the complete markdown document only — no
preamble, no explanation, no fence around the whole document.

# Absolute rules

1. **Never mention a sub-folder.** Not by name, not by link, not in prose. This
   file describes THIS folder's own code files and nothing else. A
   `## Subfolders` section is forbidden.
2. **Never invent an identifier.** Every symbol you name must appear in the
   `## Extracted symbols` block you are given (for this folder) or in the
   `## Imports` block (for an outgoing edge). If you are not sure a call happens,
   omit the branch. A partial call graph is correct; an invented edge is a lie
   that costs an agent a whole investigation.
3. **Never copy a line count or a line range from the current document.** Take
   them from the data you are given. Stale numbers are the failure mode this
   file exists to eliminate.
4. Patch, do not rewrite. Lines about unchanged files must survive verbatim.

# Required structure, in this order

## 1. Title and purpose
`# <folder>/` on the first line, then ONE sentence saying what the folder does.

## 2. `## Entry Points`
A table `| Function | File | Description |`. One row per symbol that callers
OUTSIDE this folder actually use (public API, registered hooks, CLI entry).
Every `Function` must exist in `## Extracted symbols`.

## 3. `## Main Call Graph` — required when the folder has 2+ code files
An ASCII tree rooted at the primary entry point, in a fenced block.

**Every call line MUST end with the file it lives in, in square brackets.**

```
run(user_message, state, config)
 │
 ├─ [if user_message is None]
 │   └── _complete_pending_tool_calls(pending, state, config)  [loop.py]
 │        └── _check_permission(tc, config)                    [permissions.py]
 │
 └─ while True:
     ├── stream_llm_turn(...)      → [see Zoom: stream_llm_turn]
     └── execute_tool_calls(...)   → [see Zoom: execute_tool_calls]
```

Two line shapes, and the difference is load-bearing:

- **A CALL** uses a two-dash connector `├──` / `└──` and MUST end with the file
  it lives in, in square brackets, or with `→ [see Zoom: <fn>]`. No exception.
- **A CONTROL-FLOW LABEL** uses a one-dash connector `├─` / `└─` and MUST start
  with a bracket: `├─ [if ...]`, `├─ [else]`, `└─ [for each tc]`. It carries no
  file annotation because it is not a call.

Never mix them: a line describing a branch is never `├──`, a line describing a
call is never `├─`.

More rules for the tree:
- **Indentation means "calls".** Nest B under A only when A's body actually
  calls B. Two functions invoked one after the other by the same caller are
  SIBLINGS at the same depth. Getting this wrong sends a reader to the wrong
  file.
- A call into another module is annotated with that module, e.g.
  `[context_manager/methodology]`.
- Cross-reference a big sub-flow with `→ [see Zoom: <fn>]` rather than nesting
  it inline.

## 4. `## Zoom: <fn>() — <file> L<a>-<b>` (optional, one per major function)
The line range MUST be the one given in `## Extracted symbols`. Do not compute
it yourself, do not carry one over from the current document.

## 5. `## Module Reference`
A table `| File | Lines | Purpose |`, one row per code file, sorted by name.
`Lines` is the **integer line count given to you in `## File sizes`** — copy it,
never count and never write a range. The `Purpose` cell **names real symbols with their signature** and separates
roles, e.g.:
`Public: \\`load_skills(paths)\\`, \\`find_skill(name)\\`. Hook: \\`_install(...)\\`.
Internals: \\`_iter_skill_files(dir)\\`, \\`_dedupe(defs)\\`.`
Narrative prose ("handles the tricky case where…") is NOT allowed here — this
is an index, not a history. Cap each cell at 400 characters.

## 6. `## External Dependencies`
A table `| Module | Functions used |`. **Name the functions**, never summarise
what the other module does — summarising a neighbour is what makes documents
rot in pairs. `\\`tool_registry\\` | \\`get_tool_schemas()\\`, \\`ends_turn()\\`` is
right; `\\`tool_registry\\` | keeps the tool table` is wrong.

## 7. Gotchas (optional, free prose, at the end)
Only what a parser can NEVER derive: "`resume_paused` is not re-exported —
import it from `.loop`". No line numbers here either.

# The test your output must pass

A reader must be able to pick the ONE symbol to open, from this file alone,
without opening any source file. If a section does not help that, cut it.
"""

AGENTS_SYSTEM_PROMPT = """\
You produce the repository-root `AGENTS.md`: the STRUCTURE of the repository —
which folders exist and what each is for. Output the complete markdown only.

# Absolute rules

1. **No symbol, no file name, ever.** This file says where to go, never what is
   inside. What is inside lives in each folder's own `SYMBOLS.md`.
2. **Never touch a row for a folder absent from the tree diff.** Rows you do not
   have a diff entry for must survive byte-for-byte.
3. Each `Purpose` is ONE sentence, hard cap **110 characters**.

# Required structure

`# <repo>/` then one sentence describing the repository, then:

```
## Folders

| Folder | Purpose |
|--------|---------|
| [src/pkg/backend/agent/](src/pkg/backend/agent/SYMBOLS.md) | Turn loop: streaming, tool DAG, enforcement. |
```

Rows sorted by path. The link target is always `<folder>/SYMBOLS.md`.
"""
