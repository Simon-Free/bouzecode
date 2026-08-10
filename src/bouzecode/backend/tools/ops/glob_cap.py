# [desc] Caps a Glob result to a readable head plus a directory rollup of everything it hides. [/desc]
"""Cap — NOT a guard — for the number of paths a Glob result prints.

A guard refuses a call: the agent pays a full API round-trip and learns nothing.
A cap always answers, just shorter. So `Glob` never fails here — it returns the
first `GLOB_CAP` paths, states the true total, and rolls the hidden matches up by
directory so the agent can still see WHERE the rest live and re-issue a narrower
call in the same breath.

`GLOB_CAP = 80` is measured on this repository, not guessed. The two commonest
orienting globs fit under it untouched — every module of one package
(`backend/tools/*.py` = 55) and every doc of one subsystem (`src/**/*.md` = 67) —
so a well-scoped call is never truncated. The unscoped cases that motivated the
cap (`src/**/*.py` = 380, `**/*.md` = 193) drop from ~5 000-8 000 tokens to
roughly 1 000.
"""
from __future__ import annotations

import os
from collections import Counter

GLOB_CAP = 80
_TOP_DIRS = 8


def cap_glob_matches(matches: list[str], pattern: str) -> str:
    """Render `matches` as a newline-joined list, capped at `GLOB_CAP` paths.

    Under the cap the output is exactly the full list. Over it, the head is
    followed by the true total, the reason (a cap, not a filter), and a
    directory breakdown of the paths that were left out.
    """
    if len(matches) <= GLOB_CAP:
        return "\n".join(matches)

    shown, hidden = matches[:GLOB_CAP], matches[GLOB_CAP:]
    by_dir = Counter(os.path.dirname(m) or "." for m in hidden)
    lines = [
        "\n".join(shown),
        "",
        f"[Glob: {len(matches)} files matched, showing the first {GLOB_CAP}. "
        "Nothing was filtered out — this is a display cap. To see the rest, "
        "narrow the search: a more specific pattern, or path= to scope it to "
        "one directory.]",
        f"The {len(hidden)} paths not shown are in:",
    ]
    for directory, count in by_dir.most_common(_TOP_DIRS):
        lines.append(f"  {directory}  ({count})")
    if len(by_dir) > _TOP_DIRS:
        lines.append(f"  ({len(by_dir) - _TOP_DIRS} more directories)")
    busiest = by_dir.most_common(1)[0][0]
    lines.append(f'Refine: Glob(pattern="{pattern}", path="{busiest}")')
    return "\n".join(lines)
