# [desc] Assembles what a regeneration is shown: current map, changed files in full, extracted symbols, imports, sizes. [/desc]
from __future__ import annotations

import re
from pathlib import Path

from ..folder_desc.symbols import extract_symbols
from .manifest import (
    SYMBOLS_DOC,
    code_files,
    folder_manifest,
    iter_code_folders,
    split_frontmatter,
)

_IMPORT_RE = re.compile(
    r"^[ \t]*(?:from\s+([\w.]+)\s+import\s+\(?([^()]*?)\)?$|import\s+([\w.]+))",
    re.MULTILINE | re.DOTALL,
)
_MULTILINE_IMPORT_RE = re.compile(r"from\s+([\w.]+)\s+import\s+\(([^)]*)\)", re.DOTALL)


def symbol_names(folder: Path) -> set[str]:
    """Every symbol name (and method name) defined by the folder's own files."""
    names: set[str] = set()
    for path in code_files(folder):
        for sym in extract_symbols(str(path)):
            names.add(sym.name)
            names.update(c.name for c in sym.children)
    return names


def legal_identifiers(folder: Path) -> set[str]:
    """What a call graph of this folder is allowed to name: own symbols +
    everything it imports + Python builtins. Anything else is invented."""
    import builtins

    names = symbol_names(folder) | set(dir(builtins)) | _parameter_names(folder)
    for module, imported in _import_edges(folder).items():
        names.update(imported)
        names.add(module.rsplit(".", 1)[-1])
    return names


def _parameter_names(folder: Path) -> set[str]:
    """Parameters are legal call targets: a callback passed in is invoked by name."""
    import ast

    names: set[str] = set()
    for path in sorted(folder.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.update(a.arg for a in node.args.args + node.args.kwonlyargs)
    return names


def _symbol_block(folder: Path) -> str:
    lines = []
    for path in code_files(folder):
        syms = extract_symbols(str(path))
        if not syms:
            continue
        lines.append(f"### {path.name}")
        for sym in syms:
            lines.append(f"- {sym.kind} {sym.name} L{sym.start_line}-{sym.end_line}")
            for child in sym.children:
                lines.append(f"  - def {sym.name}.{child.name} L{child.start_line}-{child.end_line}")
    return "\n".join(lines) or "(no parsable symbols)"


def _import_edges(folder: Path) -> dict[str, set[str]]:
    """``{module: {imported names}}`` over the folder's Python files.

    Parenthesised multi-line imports are matched first: missing them silently
    hides real outgoing edges and makes the validator reject honest lines.
    """
    edges: dict[str, set[str]] = {}

    def add(module: str, raw: str) -> None:
        bucket = edges.setdefault(module, set())
        bucket.update(
            n.strip().split(" as ")[-1].strip()
            for n in raw.split(",") if n.strip() and n.strip() != "*"
        )

    for path in code_files(folder):
        if path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in _MULTILINE_IMPORT_RE.finditer(text):
            add(m.group(1), m.group(2))
        for m in _IMPORT_RE.finditer(_MULTILINE_IMPORT_RE.sub("", text)):
            add(m.group(1) or m.group(3), m.group(2) or "")
    return edges


def _import_block(folder: Path) -> str:
    return "\n".join(
        f"- {mod}: {', '.join(sorted(n for n in names if n))}" if names else f"- {mod}"
        for mod, names in sorted(_import_edges(folder).items())
    ) or "(none)"


def _size_block(folder: Path) -> str:
    return "\n".join(
        f"- {name}: {entry['lines']} lines"
        for name, entry in sorted(folder_manifest(folder).items())
    ) or "(none)"


def split_changed(folder: Path, recorded: dict) -> tuple[list[Path], list[str]]:
    """``(files to send in full, names to send bare)`` — the patch-semantics split."""
    files = code_files(folder)
    if not recorded:
        return files, []
    changed = [
        p for p in files
        if recorded.get(p.name, {}).get("sha256") != folder_manifest(folder)[p.name]["sha256"]
    ]
    changed_names = {p.name for p in changed}
    return changed, [p.name for p in files if p.name not in changed_names]


def build_symbols_message(folder: Path, root: Path) -> str:
    doc = folder / SYMBOLS_DOC
    current = doc.read_text(encoding="utf-8") if doc.exists() else "(none — first generation)"
    recorded, _ = split_frontmatter(current) if doc.exists() else ({}, "")
    changed, unchanged = split_changed(folder, recorded.get("files", {}))

    rel = str(folder.relative_to(root)).replace("\\", "/") if folder != root else root.name
    parts = [f"# Folder to document: {rel}", "", "## Current SYMBOLS.md", current, ""]
    parts += ["## Changed / new files (full content)"]
    for p in changed:
        parts += [f"### {p.name}", "```", p.read_text(encoding="utf-8", errors="replace"), "```"]
    if not changed:
        parts.append("(none — all files unchanged)")
    parts += [
        "",
        "## Unchanged files (names only — copy their existing lines verbatim)",
        ", ".join(unchanged) or "(none)",
        "",
        "## Extracted symbols (deterministic — never name anything absent from this list)",
        _symbol_block(folder),
        "",
        "## File sizes (authoritative — copy these into the Lines column)",
        _size_block(folder),
        "",
        "## Imports seen in this folder (the only legal outgoing edges)",
        _import_block(folder),
        "",
        "Update SYMBOLS.md per the contract. Touch ONLY what the changed files require.",
    ]
    return "\n".join(parts)


def code_folder_paths(root: Path) -> list[str]:
    """The authoritative folder list, in the exact spelling a table row must link to.

    The root itself is excluded: it is the document, not a row in it.
    """
    return sorted(
        str(f.relative_to(root)).replace("\\", "/") + "/"
        for f in iter_code_folders(root) if f != root
    )


def build_agents_message(root: Path, current: str, diff: list[str]) -> str:
    folders = code_folder_paths(root)
    return "\n".join([
        f"# Repository: {root.name}", "", "## Current AGENTS.md", current, "",
        "## Tree diff since the last generation",
        "\n".join(diff) or "(none — first generation, list every folder below)", "",
        f"## Code folders (authoritative list — {len(folders)} rows, all of them required)",
        "\n".join(folders),
        "",
        "Update the ## Folders table. Touch NO row for a folder absent from the diff.",
        f"The table must carry all {len(folders)} rows: a map missing its tail is worse "
        "than no map, because nothing in it says a folder was left out.",
    ])


