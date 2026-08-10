# [desc] Orchestrates rendering of parsed session blocks into a self-contained HTML page, delegating to constants/markdown/diff/blocks submodules. [/desc]
"""Render parsed session blocks to a self-contained HTML page.

This module is the orchestrator: static assets live in ``constants``, markdown
conversion in ``markdown``, diff rendering in ``diff`` and per-block rendering in
``blocks``. Their public helpers are re-exported here for backward compatibility
(existing code/tests import them from ``renderer``).
"""
import html

from .parser import AssistantText, Block, SystemNotice, ToolCall, ToolResult, UserMessage
from .constants import (
    _CSS,
    _CTX_BAR_CSS,
    _DEFAULT_COLOR,
    _LANG_MAP,
    _MONACO_CDN,
    _MONACO_INIT_SCRIPT,
    _SPINNER_HTML,
    _SPINNER_STYLE,
    _THINKING_RE,
    _TOOL_COLORS,
    _TOOL_ICONS,
)
from .markdown import _guess_language, _json_script_safe, _md, _md_table
from .diff import _render_diff, _render_diff_text
from .blocks import (
    _fmt_tok,
    _format_params,
    _format_result,
    _identify_tool_groups,
    _params_table,
    _render_plan_block,
    _render_session_footer,
    _render_tool_block,
    _render_turn_stats_bar,
    _tool_summary_hint,
)

__all__ = ["render_html"]


def render_html(blocks: list[Block], finished: bool = True, meta: dict | None = None, turn_breakdowns: dict[int, dict] | None = None) -> str:
    """Render parsed blocks to a complete self-contained HTML string."""
    head = (
        '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="utf-8">'
        f'<title>Bouzecode Session</title>\n<style>\n{_CSS}\n{_CTX_BAR_CSS}\n</style></head>\n<body>\n'
    )
    parts = [head]

    if meta:
        sid = html.escape(str(meta.get("session_id", "")))
        saved = html.escape(str(meta.get("saved_at", "")))
        turns = meta.get("turn_count", "?")
        first = html.escape(str(meta.get("first_message", ""))[:100])
        parts.append(
            f'<div class="session-meta">'
            f'<strong>Session {sid}</strong> &mdash; {saved} &mdash; {turns} turns'
            f'{"<br>" + first if first else ""}'
            f'</div>'
        )

    # Build call_id -> [index, ...] queues for FIFO pairing with duplicate IDs
    _result_queues: dict[str, list[int]] = {}
    for _idx, b in enumerate(blocks):
        if isinstance(b, ToolResult):
            _result_queues.setdefault(b.call_id, []).append(_idx)

    # Pre-calculate tool-loop groups for collapsible rendering
    block_group_map, tool_groups = _identify_tool_groups(blocks)
    last_group_idx = len(tool_groups) - 1 if tool_groups else -1
    current_group = -1

    consumed_results: set[int] = set()
    _turn_counter = 0
    i = 0
    while i < len(blocks):
        block = blocks[i]

        # Handle tool-loop group boundaries
        new_group = block_group_map.get(i, -1)
        if new_group != current_group:
            if current_group >= 0:
                parts.append('</div></details>')
            if new_group >= 0:
                _, _, n_calls, names = tool_groups[new_group]
                open_attr = ' open' if new_group == last_group_idx else ''
                icons = ' '.join(_TOOL_ICONS.get(n, '&#128295;') for n in names)
                names_str = html.escape(', '.join(names))
                parts.append(
                    f'<details class="tool-loop"{open_attr}>'
                    f'<summary class="tool-loop-summary">'
                    f'<span class="tool-loop-icons">{icons}</span>'
                    f'<span class="tool-loop-label">{n_calls} tools &mdash; {names_str}</span>'
                    f'<span class="tool-loop-chevron">&#9654;</span>'
                    f'</summary>'
                    f'<div class="tool-loop-body">'
                )
            current_group = new_group

        if isinstance(block, SystemNotice):
            parts.append(
                f'<div class="system-notice"><div class="label">⚠️ System</div>'
                f'{_md(block.content)}</div>'
            )
        elif isinstance(block, UserMessage):
            _turn_counter += 1
            parts.append(
                f'<div class="user-msg"><div class="label">You</div>'
                f'{_md(block.content)}</div>'
            )
            if turn_breakdowns and _turn_counter in turn_breakdowns:
                parts.append(_render_turn_stats_bar(_turn_counter, turn_breakdowns[_turn_counter]))
        elif isinstance(block, AssistantText):
            segments = _THINKING_RE.split(block.content)
            html_parts: list[str] = []
            for idx, seg in enumerate(segments):
                seg = seg.strip()
                if not seg:
                    continue
                if idx % 2 == 1:
                    html_parts.append(f'<div class="thinking">{_md(seg)}</div>')
                else:
                    html_parts.append(f'<div class="assistant">{_md(seg)}</div>')
            parts.append("\n".join(html_parts) if html_parts else "")
        elif isinstance(block, ToolCall):
            result = None
            queue = _result_queues.get(block.call_id, [])
            if queue:
                ridx = queue.pop(0)
                result = blocks[ridx]
                consumed_results.add(ridx)
            if block.name == "WritePlan":
                parts.append(_render_plan_block(block))
            else:
                parts.append(_render_tool_block(block, result))
        elif isinstance(block, ToolResult) and i not in consumed_results:
            parts.append(f"<pre>{html.escape(block.content[:4000])}</pre>")
        i += 1

    # Close any remaining open tool-loop group
    if current_group >= 0:
        parts.append('</div></details>')

    if not finished:
        parts.append(_SPINNER_HTML)

    if finished and meta:
        parts.append(_render_session_footer(meta))

    if any("monaco-diff-box" in p for p in parts):
        parts.append(_MONACO_INIT_SCRIPT)

    parts.append("\n</body>\n</html>")
    return "\n".join(parts)
