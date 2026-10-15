# [desc] Snippetable tool_results on the wire: line numbers in the result, the "A SNIPPETER" instruction apart (for <harness_notes>). [/desc]
"""Wire-level marking of snippetable tool_results.

Tools flagged ``snippetable`` with ``snippet_key='tool_id'`` get their lines numbered
1..N over the raw content so the model's ranges line up with
``resolve_snippet_from_result`` (which slices the same raw content stored unnumbered in
the history). File-keyed tools (Read, Skill, Edit, Write) are keyed by ``file=<path>``.

The instruction (« A SNIPPETER id: … — Snippet(…) ou discard ») is returned APART from
the result: it travels in the turn's ``<harness_notes>`` block, after the tool_results.
Written inside a tool_result, harness instructions read as an injection to the gateway's
classifier (claude-opus-5-5, content_filter refusals measured on 2026-10-07).
"""
from __future__ import annotations

# Minimum line count for a tool result to be marked to snippet and subject to snippet
# enforcement. Results below this threshold are left as is and do NOT trigger
# enforcement violations.
SNIPPET_MIN_LINES = 50

# Key of a wire `role: tool` message holding its harness instruction (never sent as is:
# dispatch moves it into <harness_notes>, the converters ignore unknown keys).
HARNESS_NOTE_KEY = "_harness_note"

_FILE_SNIPPET_TOOLS = {"Read", "Skill", "Edit", "Write"}

# Tools whose results must NEVER be marked to snippet, regardless of length. (Empty:
# Edit/Write are file-keyed snippetable so their post-edit diff can be frozen like a
# Read — this kills the post-edit doubt / re-Read amnesia.)
_SNIPPET_EXEMPT_TOOLS = frozenset()


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
    """True if *tool_name* is a file-keyed snippetable tool (Read, Skill, Edit, Write)."""
    if tool_name in _SNIPPET_EXEMPT_TOOLS:
        return False
    return bool(tool_name and tool_name in _FILE_SNIPPET_TOOLS)


def _line_count(content: str) -> int:
    """Count lines in content (empty string = 0 lines)."""
    if not content:
        return 0
    return content.count("\n") + 1


def _numbered(content: str) -> str:
    return "\n".join(f"{i}\t{line}" for i, line in enumerate(content.split("\n"), 1))


def mark_snippetable(content: str, tool_id: str) -> tuple[str, str]:
    """(numbered result, instruction) for a tool_id-keyed result; unchanged and no
    instruction below SNIPPET_MIN_LINES."""
    if _line_count(content) < SNIPPET_MIN_LINES:
        return content or "", ""
    return _numbered(content), (
        f"A SNIPPETER id: tool_id={tool_id} — détruit au prochain tour. Garde les passages "
        f'utiles via Snippet(tool_id="{tool_id}", ranges=[[a,b]]) ou discard.'
    )


def mark_write_snippetable(content: str, file_path: str, tool_id: str) -> tuple[str, str]:
    """Write/Edit result: NOT renumbered — its echo already carries the file's REAL line
    numbers (renumbering 1..N would point Snippet ranges at the wrong lines on disk)."""
    if _line_count(content) < SNIPPET_MIN_LINES:
        return content or "", ""
    return content, (
        f"A SNIPPETER id: file={file_path} (résultat {tool_id}) — détruit au prochain tour. "
        f"Numéros = lignes réelles du fichier : garde les passages utiles via "
        f'Snippet(file_path="{file_path}", ranges=[[a,b]]) ou discard=true.'
    )


def mark_file_snippetable(content: str, file_path: str, tool_id: str) -> tuple[str, str]:
    """(numbered result, instruction) for a Read/Skill result, keyed by file_path."""
    if _line_count(content) < SNIPPET_MIN_LINES:
        return content or "", ""
    return _numbered(content), (
        f"A SNIPPETER id: file={file_path} (résultat {tool_id}) — détruit au prochain tour. "
        f'Garde les passages utiles via Snippet(file_path="{file_path}", ranges=[[a,b]]) '
        f"ou discard=true."
    )
