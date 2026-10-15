"""Enregistrement des outils FindCode et Tree."""
from __future__ import annotations

from pathlib import Path

from ...core.tool_registry import ToolDef, register_tool
from .index import RepoIndex, get_index, repo_root
from .search import (Query, find_exact, loaded, rank, render_neighbourhood, render_search,
                     to_load)
from .tree import render_tree

FINDCODE_SCHEMA = {
    "name": "FindCode",
    "description": (
        "Locate code in one call. Returns ranked definitions, each as "
        "`file:Lstart-end kind name(signature) — first doc line`, with their callers and "
        "callees (file:line). It indexes every definition of the repo (Python, JS/TS, "
        "<script> in .html) and is never stale: no need to Grep in parallel to double-check. "
        "`load=true` also returns the bodies of the 1-3 best matches: locate and read in the "
        "same turn. Then Read(file_path, symbol=<name shown>)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": (
                "Keywords and/or identifiers, e.g. \"snippet symbol resolve\". "
                "A few code words work better than a sentence.")},
            "symbol": {"type": "string", "description": (
                "An exact name, `name` or `Class.method`: its definition, callers and callees.")},
            "depth": {"type": "integer", "description": (
                "With symbol: 1 = direct callers/callees (default), 2 = one level further.")},
            "load": {"type": "boolean", "description": (
                "true: also return the bodies of the best 1-3 definitions (or of `symbol`).")},
            "path": {"type": "string", "description": (
                "Optional folder or file to search in (repo-relative or absolute).")},
        },
        "required": [],
    },
}

TREE_SCHEMA = {
    "name": "Tree",
    "description": (
        "Folder tree of the code, root included: code files per folder and the most "
        "referenced symbols of each. Deterministic, never stale. To locate something "
        "precise, use FindCode."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder to start from (default: repo root)."},
            "depth": {"type": "integer", "description": "Folder levels shown below it (default 2)."},
        },
        "required": [],
    },
}


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "oui")
    return bool(value)


def _int(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def locate(path: str | None) -> tuple[Path, str] | str:
    """(racine du dépôt, préfixe relatif) pour `path`, ou un message d'erreur."""
    from ...core.dossier_agent import courant
    here = repo_root(Path(courant()))
    if not path or not str(path).strip():
        return here, ""
    target = Path(str(path).strip()).expanduser()
    target = (target if target.is_absolute() else here / target).resolve()
    if not target.exists():
        return f"Error: no such file or folder: {path}"
    root = here if target.is_relative_to(here) else repo_root(target if target.is_dir() else target.parent)
    prefix = target.relative_to(root).as_posix()
    return root, "" if prefix == "." else prefix


def _symbol_mode(index: RepoIndex, symbol: str, prefix: str, depth: int, load: bool) -> str:
    targets = find_exact(index, symbol, prefix)
    if not targets:
        ranked = rank(index, Query(symbol), prefix)
        if not ranked:
            return f"FindCode: no definition named {symbol!r}, nor anything close. Try query= or Grep."
        return f"No definition named exactly {symbol!r}. Closest:\n" + render_search(index, symbol, ranked)
    out = render_neighbourhood(index, targets, depth)
    return out + ("\n\n" + loaded(index, targets[:1]) if load else "")


def findcode_tool(params: dict, config: dict) -> str:
    query = str(params.get("query") or "").strip()
    symbol = str(params.get("symbol") or "").strip()
    if not query and not symbol:
        return "Error: FindCode needs `query` (keywords or names) and/or `symbol`."
    located = locate(params.get("path"))
    if isinstance(located, str):
        return located
    root, prefix = located
    index = get_index(root)
    load = _flag(params.get("load"))
    if symbol:
        return _symbol_mode(index, symbol, prefix, _int(params.get("depth"), 1, 1, 2), load)
    ranked = rank(index, Query(query), prefix)
    if not ranked:
        return (f"FindCode {query!r}: no definition matches under {root / prefix}. "
                "Try other words or identifiers, or Grep for an exact text.")
    out = render_search(index, query, ranked)
    if params.get("depth") not in (None, ""):
        out += "\n(depth only applies with symbol=: FindCode(symbol=\"<qualname>\", depth=2).)"
    return out + (_loaded_bodies(index, ranked) if load else "")


def _loaded_bodies(index: RepoIndex, ranked) -> str:
    """Corps joints par `load=true`. Plusieurs corps = aucun premier net : on le DIT, pour que
    le modèle choisisse dans la liste au lieu de prendre le premier corps pour le bon."""
    defs = to_load(ranked)
    note = ""
    if len(defs) > 1:
        note = (f"\n\nNo clear best match: bodies of the {len(defs)} closest definitions "
                "(check the list above before relying on the first).")
    return note + "\n\n" + loaded(index, defs)


def tree_tool(params: dict, config: dict) -> str:
    located = locate(params.get("path"))
    if isinstance(located, str):
        return located
    root, prefix = located
    return render_tree(get_index(root), prefix, _int(params.get("depth"), 2, 0, 6))


register_tool(ToolDef(name="FindCode", schema=FINDCODE_SCHEMA, func=findcode_tool,
                      read_only=True, concurrent_safe=True, snippetable=True, snippet_key="tool_id"))
register_tool(ToolDef(name="Tree", schema=TREE_SCHEMA, func=tree_tool,
                      read_only=True, concurrent_safe=True, snippetable=True, snippet_key="tool_id"))
