## Codebase navigation via the AGENTS.md map

This repository ships an auto-generated AGENTS.md map. Use it to reach any symbol in
about three turns instead of blind grepping.

1. Read the ROOT `AGENTS.md` FIRST. Its `## Subfolders` table lists every code
   folder with a one-line purpose — this is your top-level index.
2. Follow the `## Subfolders` link of the folder whose purpose matches your target.
   Each folder `AGENTS.md` has a `## Module Reference` table: File | Lines | Purpose,
   where the Purpose column names the concrete symbols (functions/classes) defined
   in that file.
3. Once you have the file and symbol name, jump straight to the code with
   `Snippet(symbol="name")` (use `ClassName.method` for methods). This freezes the
   exact definition into your working memory — no need to read the whole file.

Only fall back to `Grep` / `Glob` when the map does not resolve your target (new
code without an AGENTS.md yet, or a symbol that spans several files). The map covers
source files with extensions `.py`, `.html`, `.css`, `.js`.
