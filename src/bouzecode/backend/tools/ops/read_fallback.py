# [desc] Resolves a Read whose path or symbol misses: basename fallback for paths, whole-file for an unknown symbol. [/desc]
from __future__ import annotations

import os
from pathlib import Path

_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "site-packages", "deploy_build",
}
_MAX_CANDIDATES = 8


def resolve_missing_path(file_path: str) -> tuple[str | None, list[str]]:
    """``(resolved path, candidates)`` for a path that does not exist.

    Two sources, cheapest first. The session's already-read registry is the same
    fallback `Snippet` uses, so a path that worked once keeps working. It only
    covers files read before, which is the minority case for `Read` — so a
    bounded basename walk of the working tree backs it up. A path is only
    RESOLVED when exactly one candidate matches; several candidates are returned
    for the model to choose from, which still saves the failed turn.
    """
    from ..state import find_closest_read_file

    known = find_closest_read_file(file_path)
    if known:
        return known, [known]
    matches = _walk_for_basename(os.path.basename(file_path.replace("\\", "/")))
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _walk_for_basename(basename: str) -> list[str]:
    if not basename or basename in (".", ".."):
        return []
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(Path.cwd()):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        if basename in filenames:
            found.append(str(Path(dirpath) / basename))
            if len(found) > _MAX_CANDIDATES:
                break
    return sorted(found)


def path_not_found_message(file_path: str, candidates: list[str]) -> str:
    if not candidates:
        return f"Error: file not found: {file_path}"
    listed = "\n".join(f"  {c}" for c in candidates[:_MAX_CANDIDATES])
    return (
        f"Error: file not found: {file_path}\n"
        f"Files with that name exist here — read one of these instead:\n{listed}"
    )


def whole_file_for_unknown_symbol(file_path: str, symbol: str, content: str) -> str:
    """Serve the file instead of an error when the symbol is not there.

    The agent asked for this file; refusing costs it a whole turn to ask again
    without the symbol. The header states plainly that the symbol is absent so
    the answer is never mistaken for a hit.
    """
    from ..folder_desc.symbols import extract_symbols

    names: list[str] = []
    for sym in extract_symbols(file_path, content):
        names.append(sym.name)
        names.extend(f"{sym.name}.{child.name}" for child in sym.children)
    available = ", ".join(names[:30]) if names else "(no symbols detected)"
    lines = content.splitlines(keepends=True)
    body = "".join(f"{i + 1:6}\t{line}" for i, line in enumerate(lines))
    return (
        f"Note: symbol '{symbol}' not found in {file_path} — serving the whole file "
        f"({len(lines)} lines) so you do not have to ask twice.\n"
        f"Available symbols: {available}\n\n{body}"
    )
