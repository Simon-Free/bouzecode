"""Tree : l'arborescence des dossiers de code, racine comprise, depuis l'index de FindCode.

Chaque ligne donne un dossier, son nombre de fichiers de code, et ses symboles les plus
référencés ailleurs dans le dépôt. Les dossiers plus profonds que `depth` sont comptés
dans leur ancêtre affiché.
"""
from __future__ import annotations

import posixpath
from collections import defaultdict

from .index import RepoIndex, is_test_path

MAX_LINES = 80
MAIN_SYMBOLS = 4


def _below(folder: str, base: str) -> list[str]:
    rel = folder[len(base):].strip("/") if base else folder
    return [p for p in rel.split("/") if p]


def _shown_folder(folder: str, base: str, depth: int) -> str:
    parts = _below(folder, base)
    if len(parts) <= depth:
        return folder
    return posixpath.join(base, *parts[:depth]) if base else "/".join(parts[:depth])


def main_symbols(index: RepoIndex, files: list[str]) -> list[str]:
    """Les définitions de haut niveau les plus référencées, publiques d'abord."""
    defs = [d for rel in files for d in index.files[rel].defs
            if d.kind not in ("method", "module") and not is_test_path(rel)]
    defs.sort(key=lambda d: (d.name.startswith("_"), d.kind == "const",
                             -len(index.refs_by_name.get(d.name, [])), d.name))
    return list(dict.fromkeys(d.name for d in defs))[:MAIN_SYMBOLS]


def _group(index: RepoIndex, base: str, depth: int) -> dict[str, dict]:
    nodes: dict[str, dict] = defaultdict(lambda: {"files": [], "deep": 0})
    for rel in index.files:
        folder = posixpath.dirname(rel)
        if base and folder != base and not folder.startswith(base + "/"):
            continue
        shown = _shown_folder(folder, base, depth)
        if shown == folder:
            nodes[shown]["files"].append(rel)
        else:
            nodes[shown]["deep"] += 1
    return nodes


def render_tree(index: RepoIndex, base: str = "", depth: int = 2) -> str:
    base = base.strip("/")
    nodes = _group(index, base, depth)
    if not nodes:
        return f"Tree: no code file under {index.root / base}."
    total = sum(len(n["files"]) + n["deep"] for n in nodes.values())
    lines = [f"Tree {index.root / base} (depth {depth}): {total} code files "
             "(folder/ — files here [+ deeper] — most referenced symbols):"]
    for folder in sorted(nodes):
        node = nodes[folder]
        deeper = f" [+{node['deep']} deeper]" if node["deep"] else ""
        symbols = ", ".join(main_symbols(index, node["files"]))
        lines.append(f"{folder or '.'}/ — {len(node['files'])} files{deeper}"
                     + (f" — {symbols}" if symbols else ""))
    if len(lines) > MAX_LINES:
        hidden = len(lines) - MAX_LINES
        lines = lines[:MAX_LINES] + [f"(+{hidden} folders: Tree(path=<folder>) or a smaller depth)"]
    return "\n".join(lines)
