# [desc] Renders individual session blocks (tool calls, params, diffs, results) to HTML for the session viewer. [/desc]
"""Per-block HTML rendering helpers for the session renderer."""
import html
import os

from .constants import _DEFAULT_COLOR, _TOOL_COLORS, _TOOL_ICONS
from .diff import _render_diff
from .markdown import _md
from .parser import Block, ToolCall, ToolResult
from ..stdout_filter import clean_stdout


def _params_table(params: dict[str, str]) -> str:
    if not params:
        return ""
    rows = "".join(
        f'<tr><td class="param-name">{html.escape(k)}</td>'
        f"<td><code>{html.escape(v[:500])}</code></td></tr>"
        for k, v in params.items()
    )
    return f'<table class="params">{rows}</table>'


def _format_params(call: ToolCall) -> str:
    params = call.params
    tool_name = call.name
    if tool_name == "Edit" and "old_string" in params and "new_string" in params:
        other = {k: v for k, v in params.items() if k not in ("old_string", "new_string")}
        parts = [_params_table(other)] if other else []
        parts.append(_render_diff(
            params["old_string"], params["new_string"],
            file_path=params.get("file_path", ""),
            call_id=call.call_id,
        ))
        return "\n".join(parts)
    if tool_name == "Write" and "content" in params:
        other = {k: v for k, v in params.items() if k != "content"}
        parts = [_params_table(other)] if other else []
        content = params["content"]
        if len(content) > 5000:
            content = content[:5000] + f"\n... ({len(params['content'])} chars total)"
        parts.append(f'<pre>{html.escape(content)}</pre>')
        return "\n".join(parts)
    return _params_table(params)


def _tool_summary_hint(call: ToolCall) -> str:
    """One-line hint for the summary bar (file path, command, pattern, etc.)."""
    p = call.params
    if call.name in ("Read", "Write", "Edit"):
        fp = p.get("file_path", "")
        return os.path.basename(fp) if fp else ""
    if call.name == "Bash":
        cmd = p.get("command", "")
        return f"$ {cmd[:80]}" if cmd else ""
    if call.name == "Grep":
        pat = p.get("pattern", "")
        path = os.path.basename(p.get("path", ""))
        return f'"{pat}" in {path}' if pat else ""
    if call.name == "Glob":
        return p.get("pattern", "")
    if call.name == "Skill":
        return p.get("name", "")
    if call.name == "WritePlan":
        content = p.get("content", "")
        return content.split("\n", 1)[0][:80] if content else ""
    if call.name == "Agent":
        prompt = p.get("prompt", "")
        return prompt[:60] if prompt else ""
    if call.name == "GetFolderDescription":
        fp = p.get("folder_path", "")
        return os.path.basename(fp) if fp else ""
    return ""


def _format_result(result: ToolResult) -> str:
    content = result.content
    if len(content) > 8000:
        content = content[:8000] + f"\n... ({len(result.content)} chars total)"
    if result.tool_name in ("Bash", "RunPythonTest"):
        formatted = clean_stdout(content)
    else:
        formatted = html.escape(content)
    return f'<div class="result-section"><div class="result-label">Result</div><pre>{formatted}</pre></div>'


def _render_tool_block(call: ToolCall, result: ToolResult | None) -> str:
    icon = _TOOL_ICONS.get(call.name, "&#128295;")
    color = _TOOL_COLORS.get(call.name, _DEFAULT_COLOR)
    hint = html.escape(_tool_summary_hint(call))
    hint_html = f' <span class="tool-hint">{hint}</span>' if hint else ""

    summary = (
        f'<summary style="color:{color}">'
        f'<span class="icon">{icon}</span>'
        f'<span class="tool-name">{html.escape(call.name)}</span>'
        f'<small>({html.escape(call.call_id)})</small>'
        f'{hint_html}'
        f'<span class="chevron">&#9654;</span>'
        f'</summary>'
    )
    body_parts = [_format_params(call)]
    if result:
        body_parts.append(_format_result(result))
    body = "\n".join(body_parts)
    return f'<details class="tool">\n{summary}\n<div class="tool-body">{body}</div>\n</details>'


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n:,}"
    return str(n)


def _render_plan_block(call: ToolCall) -> str:
    content = call.params.get("content", "")
    return (
        '<div class="plan-block">'
        '<div class="plan-header">&#128203; Plan</div>'
        f'<div class="plan-content">{_md(content)}</div>'
        '</div>'
    )


def _render_session_footer(meta: dict) -> str:
    from bouzecode.backend.agent.providers.registry import calc_cost
    in_tok = meta.get("total_input_tokens", 0) or 0
    out_tok = meta.get("total_output_tokens", 0) or 0
    cache_r = meta.get("total_cache_read_tokens", 0) or 0
    cache_c = meta.get("total_cache_creation_tokens", 0) or 0
    total = in_tok + out_tok + cache_r + cache_c
    if total == 0:
        return ""
    model = meta.get("model") or "claude-opus-4-6"
    cost = calc_cost(model, in_tok, out_tok, cache_r, cache_c)
    return (
        f'<div class="session-footer">'
        f'{_fmt_tok(in_tok)} input &middot; {_fmt_tok(out_tok)} output'
        f' &middot; {_fmt_tok(cache_r)} cache read &middot; {_fmt_tok(cache_c)} cache write'
        f' &middot; <strong>{_fmt_tok(total)} total</strong>'
        f' &middot; est. <strong>&euro;{cost:.2f}</strong>'
        f'</div>'
    )


def _render_turn_stats_bar(turn_num: int, bd: dict) -> str:
    total = bd["total_tokens"]
    badges = [f'<span class="ctx-badge ctx-badge-live">{bd["n_live"]} live</span>']
    if bd["n_trashed"]:
        badges.append(f'<span class="ctx-badge ctx-badge-trashed">{bd["n_trashed"]} trashed</span>')
    if bd["n_notes"]:
        badges.append(f'<span class="ctx-badge ctx-badge-notes">{bd["n_notes"]} notes</span>')
    rows = []
    for it in bd["items"]:
        s = it["status"]
        label = html.escape(it["label"][:120])
        typ = it["type"].replace("_", " ").title()
        rows.append(
            f'<tr class="ctx-row-{s}">'
            f'<td class="ctx-type">{typ}</td><td>{label}</td>'
            f'<td class="ctx-tok">{it["tokens"]:,}</td>'
            f'<td class="ctx-st"><span class="ctx-pill ctx-s-{s}">{s}</span></td></tr>'
        )
    table = (
        '<table class="ctx-table"><tr><th class="ctx-type">Type</th>'
        '<th>Item</th><th class="ctx-tok">~Tokens</th>'
        '<th class="ctx-st">Status</th></tr>' + "".join(rows) + "</table>"
    )
    return (
        f'<details class="ctx-bar"><summary>'
        f'<span>Turn {turn_num} Context</span>'
        f'<span class="ctx-tokens">~{total:,} tokens</span>'
        f'<span>{bd["n_items"]} items</span>'
        f'{" ".join(badges)}'
        f'</summary>{table}</details>'
    )


def _identify_tool_groups(
    blocks: list[Block],
) -> tuple[dict[int, int], list[tuple[int, int, int, list[str]]]]:
    """Pre-scan blocks to find consecutive tool-call groups for collapsible rendering.

    Returns (block_group_map, groups) where:
    - block_group_map: block_idx -> group_idx (only for blocks in multi-call groups)
    - groups: list of (start, end_exclusive, n_calls, unique_names)
    """
    result_queues: dict[str, list[int]] = {}
    for idx, b in enumerate(blocks):
        if isinstance(b, ToolResult):
            result_queues.setdefault(b.call_id, []).append(idx)

    consumed: set[int] = set()
    result_call_name: dict[int, str] = {}
    queues_copy = {k: list(v) for k, v in result_queues.items()}
    for idx, b in enumerate(blocks):
        if isinstance(b, ToolCall):
            queue = queues_copy.get(b.call_id, [])
            if queue:
                ridx = queue.pop(0)
                consumed.add(ridx)
                result_call_name[ridx] = b.name

    is_tool = [
        (isinstance(b, ToolCall) and b.name != "WritePlan")
        or (isinstance(b, ToolResult) and idx in consumed and result_call_name.get(idx) != "WritePlan")
        for idx, b in enumerate(blocks)
    ]

    all_groups: list[tuple[int, int, int, list[str]]] = []
    i = 0
    while i < len(blocks):
        if is_tool[i]:
            start = i
            n_calls = 0
            names: list[str] = []
            while i < len(blocks) and is_tool[i]:
                if isinstance(blocks[i], ToolCall):
                    n_calls += 1
                    if blocks[i].name not in names:
                        names.append(blocks[i].name)
                i += 1
            all_groups.append((start, i, n_calls, names))
        else:
            i += 1

    multi = [(s, e, n, ns) for s, e, n, ns in all_groups if n >= 2]
    block_map: dict[int, int] = {}
    for gi, (start, end, _, _) in enumerate(multi):
        for idx in range(start, end):
            block_map[idx] = gi
    return block_map, multi
