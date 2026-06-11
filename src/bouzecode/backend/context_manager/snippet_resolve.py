# [desc] Resolve Snippet ranges from a file on disk or an inline tool_result. [/desc]
"""Resolve labeled line ranges for the Snippet tool.

Two sources, one renderer:
- a file on disk (Read/Skill snippets, keyed by file_path)
- an inline tool_result content string from the message history (keyed by tool_id)
"""
from __future__ import annotations

import re
from pathlib import Path


def _render_ranges(
    lines: list, ranges: list, label: str, source: str, resolution_note: str = "",
) -> str:
    """Render labeled 1-indexed line ranges as markdown snippet blocks."""
    out = []
    for rng in ranges or []:
        if not isinstance(rng, list) or len(rng) != 2:
            out.append(f"## snippet ERROR: {source} — invalid range {rng!r}\n")
            continue
        start, end = rng
        if start < 1:
            start = 1
        if end > len(lines):
            end = len(lines)
        if start > end:
            out.append(f"## snippet ERROR: {source} L{rng[0]}-{rng[1]} — empty range\n")
            continue
        suffix = f' — "{label}"' if label else ""
        body = "\n".join(f"{i:>5}  {lines[i-1]}" for i in range(start, end + 1))
        out.append(f"## snippet: {source} L{start}-{end}{suffix}{resolution_note}\n{body}\n")
    return "\n" + "\n".join(out)


def resolve_snippet_symbol(file_path: str, symbol: str, label: str = "") -> str:
    """Resolve a symbol-based snippet: find symbol lines dynamically and render.

    Returns a markdown block with header ``## snippet: <path> :: <symbol>``.
    If the symbol cannot be found, returns an error block.
    """
    from ..tools.folder_desc.symbols import find_symbol

    path = Path(file_path)
    if not path.is_absolute():
        return f"\n## snippet ERROR: {file_path} — path must be absolute\n"
    if not path.exists():
        return f"\n## snippet ERROR: {file_path} — file not found\n"
    content = path.read_text(encoding="utf-8", errors="replace")
    result = find_symbol(file_path, symbol, content)
    if result is None:
        return f"\n## snippet ERROR: {file_path} :: {symbol} — symbol not found\n"
    start, end = result
    lines = content.splitlines()
    suffix = f' — "{label}"' if label else ""
    body = "\n".join(f"{i:>5}  {lines[i-1]}" for i in range(start, end + 1))
    return f"\n## snippet: {file_path} :: {symbol}{suffix}\n{body}\n"


_SYMBOL_SNIPPET_RE = re.compile(
    r"^## snippet: (?P<path>.+?) :: (?P<symbol>\S+?)(?:\s*—\s*\"(?P<label>[^\"]*)\")?\n"
    r"(?P<body>(?:.*\n)*?)(?=\n## |\Z)",
    re.MULTILINE,
)


def refresh_symbol_snippets(methodology_text: str) -> str:
    """Re-resolve all symbol-based snippets in methodology text.

    Only mutates a block's body if the source file actually changed.
    Returns the (possibly updated) methodology text.
    """
    from ..tools.folder_desc.symbols import find_symbol

    def _replace(m: re.Match) -> str:
        file_path = m.group("path")
        symbol = m.group("symbol")
        label = m.group("label") or ""
        old_block = m.group(0)

        path = Path(file_path)
        if not path.exists():
            return old_block  # keep stale block rather than error

        content = path.read_text(encoding="utf-8", errors="replace")
        result = find_symbol(file_path, symbol, content)
        if result is None:
            return old_block  # symbol removed — keep stale rather than error

        start, end = result
        lines = content.splitlines()
        suffix = f' — "{label}"' if label else ""
        body = "\n".join(f"{i:>5}  {lines[i-1]}" for i in range(start, end + 1))
        new_block = f"## snippet: {file_path} :: {symbol}{suffix}\n{body}\n"

        if new_block == old_block:
            return old_block  # unchanged — cache-safe
        return new_block

    return _SYMBOL_SNIPPET_RE.sub(_replace, methodology_text)


def resolve_snippet(file_path: str, ranges: list, label: str) -> str:
    """Read the file and return labeled line ranges as a markdown block."""
    path = Path(file_path)
    if not path.is_absolute():
        return f"\n## snippet ERROR: {file_path} — path must be absolute\n"
    resolution_note = ""
    if not path.exists():
        from ..tools.state import find_closest_read_file, list_read_files_with_basename
        fallback = find_closest_read_file(file_path)
        if fallback is None:
            candidates = list_read_files_with_basename(path.name)
            if len(candidates) > 1:
                joined = "\n  - ".join(candidates)
                return (
                    f"\n## snippet ERROR: {file_path} — file not found; "
                    f"multiple read files share this basename (ambiguous):\n  - {joined}\n"
                )
            return f"\n## snippet ERROR: {file_path} — file not found\n"
        resolution_note = f" (auto-resolved from {file_path})"
        path = Path(fallback)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return _render_ranges(lines, ranges, label, str(path), resolution_note)


def find_tool_result_content(messages: list, tool_id: str) -> str | None:
    """Return the raw content of the tool_result with the given tool_call id.

    Reads from the message history (state.messages), where tool outputs are
    stored verbatim — the wire-level snippet wrapping is never persisted there.
    """
    for msg in messages or []:
        if msg.get("role") == "tool" and msg.get("tool_call_id") == tool_id:
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            return content or ""
    return None


def resolve_snippet_from_result(content: str, ranges: list, label: str, source: str) -> str:
    """Freeze labeled line range(s) from an inline tool_result content string.

    Line numbers are 1-indexed over ``content.split("\\n")``, matching the
    numbering the wire shows the model.
    """
    return _render_ranges(content.split("\n"), ranges, label, source)
