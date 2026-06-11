# [desc] Wrap snippetable tool_results on the wire with markers + line numbers. [/desc]
"""Wire-level wrapping of snippetable tool_results.

Tools flagged ``snippetable`` with ``snippet_key='tool_id'`` have their results
wrapped between markers that tell the model the exact id to pass to
``Snippet(tool_id=...)``. Lines are numbered 1..N over the raw content so the
model's ranges line up with ``resolve_snippet_from_result`` (which slices the
same raw content stored unwrapped in the history).

File-keyed tools (Read, Skill) are wrapped with ``id: file=<path>`` markers so
the model knows both the file_path AND that it must Snippet or discard.
"""
from __future__ import annotations

# Minimum line count for a tool result to be wrapped with snippet markers
# and subject to snippet enforcement. Results below this threshold are left
# unwrapped and do NOT trigger enforcement violations.
SNIPPET_MIN_LINES = 50

_SNIPPET_OPEN = "==== A SNIPPETER id: tool_id={tool_id} ===="
_FILE_SNIPPET_OPEN = "==== A SNIPPETER id: file={file_path} ===="
_SNIPPET_CLOSE = "==== FIN DE L'ELEMENT A SNIPPETER ===="

_FILE_SNIPPET_TOOLS = {"Read", "Skill"}

# Tools whose results must NEVER be wrapped with snippet markers,
# regardless of length. Edit/Write results are transient confirmations,
# not reference material worth snippeting.
_SNIPPET_EXEMPT_TOOLS = frozenset({"Edit", "Write"})


def is_snippetable_tool_id(tool_name: str | None) -> bool:
    """True if *tool_name* is a registered tool whose result is snippeted by tool_id."""
    if not tool_name:
        return False
    if tool_name in _SNIPPET_EXEMPT_TOOLS:
        return False
    from ..core.tool_registry import get_tool
    tool = get_tool(tool_name)
    return bool(
        tool
        and getattr(tool, "snippetable", False)
        and getattr(tool, "snippet_key", "tool_id") == "tool_id"
    )


def is_file_snippetable(tool_name: str | None) -> bool:
    """True if *tool_name* is Read or Skill (file-keyed snippetable tools)."""
    if tool_name in _SNIPPET_EXEMPT_TOOLS:
        return False
    return bool(tool_name and tool_name in _FILE_SNIPPET_TOOLS)


def _line_count(content: str) -> int:
    """Count lines in content (empty string = 0 lines)."""
    if not content:
        return 0
    return content.count("\n") + 1


def wrap_snippetable(content: str, tool_id: str) -> str:
    """Wrap a snippetable tool_result with markers + 1-indexed line numbers.

    Returns content unchanged if it has fewer than SNIPPET_MIN_LINES lines.
    """
    if _line_count(content) < SNIPPET_MIN_LINES:
        return content or ""
    lines = (content or "").split("\n")
    numbered = "\n".join(f"{i}\t{line}" for i, line in enumerate(lines, 1))
    return (
        f"{_SNIPPET_OPEN.format(tool_id=tool_id)}\n"
        f"[SYSTEM] Détruit au prochain tour. Garde les passages utiles via "
        f'Snippet(tool_id="{tool_id}", ranges=[[a,b]]) ou discard.\n'
        f"{numbered}\n"
        f"{_SNIPPET_CLOSE}"
    )


def wrap_file_snippetable(content: str, file_path: str) -> str:
    """Wrap a Read/Skill tool_result with file-keyed markers + line numbers.

    Returns content unchanged if it has fewer than SNIPPET_MIN_LINES lines.
    The marker tells the model the exact file_path to pass to
    Snippet(file_path=..., ranges=[[a,b]]).
    """
    if _line_count(content) < SNIPPET_MIN_LINES:
        return content or ""
    lines = (content or "").split("\n")
    numbered = "\n".join(f"{i}\t{line}" for i, line in enumerate(lines, 1))
    return (
        f"{_FILE_SNIPPET_OPEN.format(file_path=file_path)}\n"
        f"[SYSTEM] Détruit au prochain tour. Garde les passages utiles via "
        f'Snippet(file_path="{file_path}", ranges=[[a,b]]) ou discard=true.\n'
        f"{numbered}\n"
        f"{_SNIPPET_CLOSE}"
    )
