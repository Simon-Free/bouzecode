# [desc] Registers folder-description tool and hooks file writes to auto-update inline descriptions. [/desc]
from __future__ import annotations

import threading
from pathlib import Path

from tool_registry import ToolDef, register_tool
from folder_desc.desc_utils import (
    EXT_TO_STYLE,
    wrap_description,
    extract_description,
    _find_desc_line_range,
)
from folder_desc.analyzer import (
    _call_llm_for_description,
    _collect_code_files,
    _analyze_folder,
    _count_files_with_description,
)

_DESCRIPTION_COVERAGE_THRESHOLD = 0.5


def _get_folder_description(params: dict, config: dict) -> str:
    folder = params["folder_path"]
    root = Path(folder)
    if not root.is_dir():
        return f"Error: {folder} is not a directory"

    code_files = _collect_code_files(root)
    if not code_files:
        return f"No code files found in {folder}"

    auto_analyzed_note = ""
    coverage = _count_files_with_description(code_files) / len(code_files)
    if coverage < _DESCRIPTION_COVERAGE_THRESHOLD:
        analysis_result = _analyze_folder({"folder_path": folder}, config)
        auto_analyzed_note = f"[Auto-analyzed] {analysis_result}\n\n"

    lines = [f"{root.name}/"]
    for p in sorted(code_files):
        rel = p.relative_to(root)
        depth = len(rel.parts) - 1
        indent = "  " * depth
        content = p.read_text(encoding="utf-8", errors="replace")
        desc, _, _ = extract_description(content)
        tag = f" -- {desc}" if desc else ""
        lines.append(f"  {indent}{rel.name}{tag}")

    return auto_analyzed_note + "\n".join(lines)


def _install_write_hook() -> None:
    from tool_registry import get_tool
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
            "one-line descriptions. If descriptions are missing, they are generated "
            "automatically (parallel LLM calls) before the tree is returned. "
            "Useful for understanding a codebase at a glance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Absolute path to the folder to describe",
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
