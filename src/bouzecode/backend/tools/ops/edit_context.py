# [desc] Post-edit enrichment: numbered region around the applied change plus its enclosing symbol. [/desc]
"""What an Edit result shows AFTER the write succeeded.

Purely decorative: the file is already on disk when these run, so nothing here
may raise its way out and turn a successful write into an error the model would
try to redo.
"""
from __future__ import annotations

_MAX_REGION_LINES = 40


def find_enclosing_symbol(file_path: str, line_no: int, content: str) -> str | None:
    """Return 'Class.method' or 'function' name enclosing line_no (1-based).

    A parser blowing up (tree-sitter ABI mismatch on a .ts file) degrades to
    "no symbol name" rather than failing an edit that already happened.
    """
    from ..folder_desc.symbols import extract_symbols
    try:
        symbols = extract_symbols(file_path, content)
    except Exception:
        return None
    for sym in symbols:
        if sym.start_line <= line_no <= sym.end_line:
            for child in sym.children:
                if child.start_line <= line_no <= child.end_line:
                    return f"{sym.name}.{child.name}"
            return sym.name
    return None


def build_edit_context(content: str, new_string: str, context_lines: int = 10) -> str:
    """Build numbered context around new_string in content. Truncate middle if huge."""
    lines = content.split("\n")
    new_norm = new_string.replace("\r\n", "\n")
    idx = content.find(new_norm)
    if idx == -1:
        return ""
    start_line = content[:idx].count("\n")
    end_line = start_line + new_norm.count("\n")

    ctx_start = max(0, start_line - context_lines)
    ctx_end = min(len(lines) - 1, end_line + context_lines)
    region = lines[ctx_start:ctx_end + 1]

    if len(region) <= _MAX_REGION_LINES:
        return "\n".join(f"{ctx_start + i + 1:6}\t{line}" for i, line in enumerate(region))

    keep_top = _MAX_REGION_LINES // 2
    keep_bot = _MAX_REGION_LINES - keep_top
    omitted = len(region) - keep_top - keep_bot
    region = region[:keep_top] + [f"    ... ({omitted} lines omitted) ..."] + region[-keep_bot:]
    numbered = [f"{ctx_start + i + 1:6}\t{line}" for i, line in enumerate(region[:keep_top])]
    numbered.append(f"{'':6}\t{region[keep_top]}")
    numbered += [f"{ctx_end + 1 - keep_bot + i:6}\t{line}"
                 for i, line in enumerate(region[keep_top + 1:])]
    return "\n".join(numbered)
