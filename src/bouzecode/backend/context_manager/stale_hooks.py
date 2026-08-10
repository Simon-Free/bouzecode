"""Post-execution hooks that mark snippets as stale after Edit/Write.

When an Edit or Write succeeds on a file that has snippets (range- OR
symbol-based) in the methodology note, a stale marker is appended (append-only,
cache-safe). Snippet bodies are NEVER rewritten in place — that would drift the
prompt-cache prefix. The next compaction pass purges both marker and snippet.
"""
from __future__ import annotations

import re
from .state import resolve_context_state, METHODOLOGY_NOTE, ContextState
from .readme_stale import mark_readme_stale

# Matches snippet headers, range-based (L<start>-<end>) or symbol-based (:: <symbol>).
_SNIPPET_RE = re.compile(
    r"^## snippet: (?P<path>.+?)"
    r"(?: L(?P<start>\d+)-(?P<end>\d+)| :: (?P<symbol>[^\s—]+))",
    re.MULTILINE,
)

_hooks_installed = False


def _mark_stale_snippets(ctx_state: ContextState, edited_path: str) -> None:
    """Append stale markers for any snippet (range or symbol) covering *edited_path*."""
    note = ctx_state.notes.get(METHODOLOGY_NOTE, "")
    if not note:
        return

    # Normalize path for comparison (case-insensitive on Windows, forward slashes)
    norm_edited = edited_path.replace("\\", "/").lower()

    markers: list[str] = []
    for m in _SNIPPET_RE.finditer(note):
        snippet_path = m.group("path").replace("\\", "/").lower()
        if snippet_path != norm_edited:
            continue
        if m.group("symbol"):
            stale_key = f"## snippet-stale: {m.group('path')} :: {m.group('symbol')}"
        else:
            stale_key = f"## snippet-stale: {m.group('path')} L{m.group('start')}-{m.group('end')}"
        # Only mark if not already marked stale
        if stale_key not in note:
            markers.append(
                f"{stale_key} — STALE (file edited; re-read or re-snippet)"
            )

    if markers:
        current = ctx_state.notes.get(METHODOLOGY_NOTE, "")
        joiner = "\n\n" if current else ""
        ctx_state.notes[METHODOLOGY_NOTE] = current.rstrip() + joiner + "\n".join(markers)


def install_stale_hooks() -> None:
    """Wrap Edit/Write tool functions to mark stale snippets after successful execution."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    from ..core.tool_registry import get_tool

    # Hook Edit
    edit_tool = get_tool("Edit")
    if edit_tool:
        original_edit = edit_tool.func

        def hooked_edit(params, config):
            result = original_edit(params, config)
            if not result.startswith("Error"):
                mark_readme_stale(params.get("file_path", ""))
                ctx_state = resolve_context_state(config)
                if ctx_state:
                    _mark_stale_snippets(ctx_state, params.get("file_path", ""))
            return result

        edit_tool.func = hooked_edit

    # Hook Write
    write_tool = get_tool("Write")
    if write_tool:
        original_write = write_tool.func

        def hooked_write(params, config):
            result = original_write(params, config)
            if not result.startswith("Error"):
                mark_readme_stale(params.get("file_path", ""))
                ctx_state = resolve_context_state(config)
                if ctx_state:
                    _mark_stale_snippets(ctx_state, params.get("file_path", ""))
            return result

        write_tool.func = hooked_write
