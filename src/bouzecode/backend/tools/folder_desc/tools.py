# [desc] Registers folder-description tool and hooks file writes to auto-update inline descriptions. [/desc]
from __future__ import annotations

import threading
from pathlib import Path

from ...core.tool_registry import ToolDef, register_tool
from ..folder_desc.desc_utils import (
    EXT_TO_STYLE,
    wrap_description,
    extract_description,
    _find_desc_line_range,
)
from ..folder_desc.analyzer import (
    _call_llm_for_description,
    _collect_code_files,
    _analyze_files,
)


def _get_folder_description(params: dict, config: dict) -> str:
    folder = params["folder_path"]
    root = Path(folder)
    if not root.is_dir():
        return f"Error: {folder} is not a directory"

    max_depth = params.get("max_depth", 2)

    code_files = _collect_code_files(root)
    if not code_files:
        return f"No code files found in {folder}"

    # Filter by depth
    filtered_files = []
    excluded_count = 0
    for p in code_files:
        rel = p.relative_to(root)
        depth = len(rel.parts) - 1
        if depth <= max_depth:
            filtered_files.append(p)
        else:
            excluded_count += 1

    file_contents: dict[Path, str] = {}
    file_descs: dict[Path, str | None] = {}
    for p in filtered_files:
        content = p.read_text(encoding="utf-8", errors="replace")
        file_contents[p] = content
        desc, _, _ = extract_description(content)
        file_descs[p] = desc

    missing = [p for p, desc in file_descs.items() if desc is None]
    auto_note = ""
    if missing:
        result = _analyze_files(missing, root, config)
        auto_note = f"[Auto-analyzed {len(missing)} files] {result}\n\n"
        for p in missing:
            content = p.read_text(encoding="utf-8", errors="replace")
            file_contents[p] = content
            desc, _, _ = extract_description(content)
            file_descs[p] = desc

    from ..folder_desc.symbols import extract_symbols, _SYMBOL_EXTS

    lines = [f"{root.name}/"]
    for p in sorted(filtered_files):
        rel = p.relative_to(root)
        depth = len(rel.parts) - 1
        indent = "  " * depth
        desc = file_descs.get(p)
        tag = f" -- {desc}" if desc else ""
        lines.append(f"  {indent}{rel.name}{tag}")

        if p.suffix.lower() in _SYMBOL_EXTS:
            content = file_contents.get(p, "")
            for sym in extract_symbols(str(p), content):
                paren = "()" if sym.kind != "class" else ""
                doc = f" -- {sym.docstring}" if sym.docstring else ""
                lines.append(f"  {indent}  {sym.kind} {sym.name}{paren}{doc}  [L{sym.start_line}-{sym.end_line}]")
                for child in sym.children:
                    cdoc = f" -- {child.docstring}" if child.docstring else ""
                    lines.append(f"  {indent}    {child.kind} {child.name}(){cdoc}  [L{child.start_line}-{child.end_line}]")

    if excluded_count:
        lines.append(f"\n  [{excluded_count} files at depth > {max_depth} not shown — use max_depth param to expand]")

    return auto_note + "\n".join(lines)


def _install_write_hook() -> None:
    from ...core.tool_registry import get_tool
    write_tool = get_tool("Write")
    if not write_tool:
        return
    original_write = write_tool.func

    def hooked_write(params: dict, config: dict) -> str:
        result = original_write(params, config)
        fp = params.get("file_path", "")
        if fp:
            threading.Thread(
                target=_maybe_update_desc, args=(fp, config), daemon=True
            ).start()
        return result

    write_tool.func = hooked_write


def _maybe_update_desc(file_path: str, config: dict | None = None) -> None:
    p = Path(file_path)
    if not p.is_file():
        return
    ext = p.suffix.lower()
    if ext not in EXT_TO_STYLE:
        return
    content = p.read_text(encoding="utf-8", errors="replace")
    rng = _find_desc_line_range(content)
    if rng is None:
        return
    lines = content.splitlines(keepends=True)
    start, end = rng
    content_without_desc = "".join(lines[:start] + lines[end:])
    new_desc = _call_llm_for_description(file_path, content_without_desc, ext, config)
    if not new_desc:
        return
    wrapped = wrap_description(new_desc, ext)
    if not wrapped:
        return
    new_lines = lines[:start] + [wrapped + "\n"] + lines[end:]
    p.write_text("".join(new_lines), encoding="utf-8", newline="")


register_tool(ToolDef(
    name="GetFolderDescription",
    schema={
        "name": "GetFolderDescription",
        "description": (
            "Return a recursive tree of code files in a folder with their [desc] "
            "one-line descriptions and symbol outlines (functions, classes, methods "
            "with docstrings and line ranges) for Python and JS/TS files. "
            "If descriptions are missing, they are generated automatically. "
            "Use this to discover symbols, then Read(symbol='...') for details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Absolute path to the folder to describe",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to include (default 2). Use higher values for deep exploration.",
                },
            },
            "required": ["folder_path"],
        },
    },
    func=_get_folder_description,
    read_only=True,
    concurrent_safe=True,
))

_install_write_hook()
