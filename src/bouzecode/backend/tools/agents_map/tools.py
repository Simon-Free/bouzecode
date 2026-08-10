# [desc] Registers the two code-navigation tools: AgentsMap (which folder) and SymbolMap (which symbol). [/desc]
"""The model-facing surface of the code maps.

`serve.symbol_map` / `serve.agents_map` hold the whole cache protocol; these two
handlers only turn a model-supplied path into the (folder, root) pair they need.
"""
from __future__ import annotations

from pathlib import Path

from ...core.tool_registry import ToolDef, register_tool
from .serve import agents_map, symbol_map

_AGENTS_MAP_SCHEMA = {
    "name": "AgentsMap",
    "description": (
        "Repository structure map: every code folder and one sentence on what it holds. "
        "Pick the folder here, then SymbolMap(path=...) to pick the symbol. "
        "Skip it when you already know the file."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_SYMBOL_MAP_SCHEMA = {
    "name": "SymbolMap",
    "description": (
        "Symbol map of ONE folder: its entry points, a call graph naming the file of "
        "each call, and every symbol with its exact line range. Read it INSTEAD of "
        "opening the files, then Read(symbol='...') the single symbol it points to. "
        "Cached against the folder's hashes: unchanged code costs nothing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Folder to map; a file path maps the folder holding it. "
                    "Direct code files only — sub-folders have their own map."
                ),
            },
        },
        "required": ["path"],
    },
}


def repo_root() -> Path:
    """The worktree root: nearest ancestor carrying a `.git` (file or directory)."""
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _agents_map_tool(params: dict, config: dict) -> str:
    return agents_map(repo_root())


def _symbol_map_tool(params: dict, config: dict) -> str:
    root = repo_root()
    folder = Path(params["path"]).expanduser()
    if not folder.is_absolute():
        folder = root / folder
    folder = folder.resolve()
    if folder.is_file():
        # The model named the file it wants; the map of its folder is what answers.
        folder = folder.parent
    if not folder.is_dir():
        return f"Error: no such folder: {params['path']}"
    if folder != root and not folder.is_relative_to(root):
        # Outside the worktree: the folder is its own frame of reference, otherwise
        # `relative_to` would raise while building the regeneration message.
        root = folder.parent
    return symbol_map(folder, root)


register_tool(ToolDef(
    name="AgentsMap",
    schema=_AGENTS_MAP_SCHEMA,
    func=_agents_map_tool,
    read_only=True,
    concurrent_safe=True,
    snippetable=True,
    snippet_key="tool_id",
))

register_tool(ToolDef(
    name="SymbolMap",
    schema=_SYMBOL_MAP_SCHEMA,
    func=_symbol_map_tool,
    read_only=True,
    concurrent_safe=True,
    snippetable=True,
    snippet_key="tool_id",
))
