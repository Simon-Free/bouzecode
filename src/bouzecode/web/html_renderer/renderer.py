# [desc] Renders parsed session blocks into self-contained HTML with rich tool display, diffs, and markdown. [/desc]
# [desc] Renders parsed session blocks into self-contained HTML with rich tool display, diffs, and markdown.
"""Render parsed session blocks to a self-contained HTML page."""
import difflib
import html
import json
import os
import re

from .parser import AssistantText, Block, SystemNotice, ToolCall, ToolResult, UserMessage
from bouzecode.web.stdout_filter import clean_stdout

_THINKING_RE = re.compile(r'(?:^|\n)[ \t]*<thinking>[ \t]*\n?(.*?)\n?[ \t]*</thinking>[ \t]*(?:\n|$)', re.DOTALL)

_TOOL_ICONS = {
    "Read": "&#128196;", "Write": "&#9999;", "Edit": "&#9998;",
    "Bash": "&#128187;", "Grep": "&#128269;", "Glob": "&#128194;",
    "WebFetch": "&#127760;", "WebSearch": "&#127760;",
    "Agent": "&#129302;", "SendMessage": "&#128172;",
    "EnterPlanMode": "&#128203;", "ExitPlanMode": "&#128203;", "WritePlan": "&#128203;",
    "MemorySave": "&#128190;", "MemorySearch": "&#128190;",
    "GetFolderDescription": "&#128194;", "GetDiagnostics": "&#9888;",
    "Skill": "&#9889;", "SkillList": "&#9889;",
    "TaskCreate": "&#9745;", "TaskUpdate": "&#9745;", "TaskList": "&#9745;",
}
_TOOL_COLORS = {
    "Read": "#0969da", "Write": "#0969da", "Edit": "#0969da",
    "Bash": "#bf5700", "Grep": "#1a7f37", "Glob": "#1a7f37",
    "WebFetch": "#6f42c1", "WebSearch": "#6f42c1",
    "Agent": "#953800", "EnterPlanMode": "#5e4b8a",
    "ExitPlanMode": "#5e4b8a", "WritePlan": "#5e4b8a", "Skill": "#7d4e00",
    "GetFolderDescription": "#1a7f37", "GetDiagnostics": "#cf222e",
}
_DEFAULT_COLOR = "#555"

_LANG_MAP = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".html": "html", ".htm": "html",
    ".css": "css", ".json": "json", ".md": "markdown", ".yaml": "yaml",
    ".yml": "yaml", ".xml": "xml", ".sh": "shell", ".bash": "shell",
    ".sql": "sql", ".java": "java", ".rs": "rust", ".go": "go",
    ".rb": "ruby", ".toml": "toml", ".ini": "ini", ".cfg": "ini",
}


def _guess_language(file_path: str) -> str:
    if not file_path:
        return "plaintext"
    return _LANG_MAP.get(os.path.splitext(file_path)[1].lower(), "plaintext")


def _json_script_safe(s: str) -> str:
    """JSON-encode a string, safe for embedding inside a &lt;script&gt; tag."""
    return json.dumps(s).replace("</", "<\\/")


# ── CSS ─────────────────────────────────────────────────────────────
_CSS = """\
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;max-width:960px;margin:0 auto;
  padding:2rem;background:#f5f7fa;color:#1f2328;line-height:1.6}
.user-msg{background:#dbeafe;border-left:4px solid #2563eb;padding:.75rem 1rem;
  border-radius:0 8px 8px 0;margin:1.2rem 0}
.user-msg .label{font-weight:700;color:#1e40af;font-size:.8rem;text-transform:uppercase;
  letter-spacing:.5px;margin-bottom:.25rem}
.assistant{margin:1.2rem 0;margin-left:1.5rem}
.assistant p{margin:.4em 0}
.assistant ul,.assistant ol{margin:.4em 0 .4em 1.5em}
details.tool{margin:.5rem 0;margin-left:3rem;border:1px solid #d1d9e0;border-radius:8px;background:#fff;
  box-shadow:0 1px 3px rgba(0,0,0,.06)}
details.tool>summary{padding:.6rem 1rem;cursor:pointer;font-weight:600;
  font-family:ui-monospace,monospace;font-size:.9rem;border-radius:8px;
  list-style:none;display:flex;align-items:center;gap:.5rem}
details.tool>summary::-webkit-details-marker{display:none}
details.tool>summary .icon{font-size:1.1em}
details.tool>summary .tool-name{font-weight:700}
details.tool>summary .tool-hint{color:#656d76;font-weight:400;font-size:.85rem;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
details.tool>summary .chevron{margin-left:auto;transition:transform .2s;color:#888;font-size:.7em}
details.tool[open]>summary .chevron{transform:rotate(90deg)}
details.tool[open]>summary{border-bottom:1px solid #d1d9e0;border-radius:8px 8px 0 0}
.tool-body{padding:1rem;overflow-x:auto}
pre{background:#1e1e2e;color:#cdd6f4;padding:1rem;border-radius:6px;overflow-x:auto;
  font-family:ui-monospace,monospace;font-size:.82rem;margin:.5rem 0;line-height:1.5}
.diff-add{background:#dafbe1;color:#1a7f37}.diff-del{background:#ffebe9;color:#cf222e}
.diff-hdr{color:#656d76;font-style:italic}
.diff-line{font-family:ui-monospace,monospace;white-space:pre;font-size:.82rem;
  padding:1px 8px;display:block}
.params{border-collapse:collapse;margin:.25rem 0;font-size:.88rem}
.params td{vertical-align:top;padding:3px 10px}
.param-name{color:#0969da;font-weight:600;font-family:ui-monospace,monospace}
.result-section{margin-top:.75rem;border-top:1px solid #eee;padding-top:.5rem}
.result-label{font-weight:600;color:#656d76;font-size:.85rem;margin-bottom:.25rem}
.monaco-diff-box{border:1px solid #d1d9e0;border-radius:6px;overflow:hidden;margin:.5rem 0}
.monaco-diff-box .diff-fallback{margin:0;border:none;box-shadow:none;border-radius:0}
h1,h2,h3{margin:.6em 0 .3em}
code{background:#eff1f3;padding:2px 6px;border-radius:4px;font-size:.88em;
  font-family:ui-monospace,monospace}
table.md-table{border-collapse:collapse;margin:.5rem 0;font-size:.9rem;width:100%}
table.md-table th,table.md-table td{border:1px solid #d1d9e0;padding:6px 12px;text-align:left}
table.md-table th{background:#f0f3f6;font-weight:600}
table.md-table tr:nth-child(even){background:#f8f9fa}
.session-meta{color:#656d76;font-size:.85rem;margin-bottom:1.5rem;
  padding-bottom:.75rem;border-bottom:1px solid #d1d9e0}
.session-footer{color:#656d76;font-size:.85rem;margin-top:1.5rem;
  padding-top:.75rem;border-top:1px solid #d1d9e0;text-align:center}
.plan-block{background:linear-gradient(135deg,#f0ebff 0%,#e8f4fd 100%);
  border:1px solid #c4b5fd;border-radius:8px;margin:1rem 0 1rem 1.5rem;overflow:hidden}
.plan-header{background:rgba(94,75,138,.1);padding:.6rem 1rem;font-weight:700;
  color:#5e4b8a;font-size:.95rem;border-bottom:1px solid #c4b5fd;
  display:flex;align-items:center;gap:.5rem}
.plan-content{padding:1rem 1.25rem}
.plan-content h1,.plan-content h2,.plan-content h3{color:#5e4b8a}
.plan-content ul{margin:.5em 0 .5em 1.5em}
.plan-content li{margin:.3em 0}
.plan-content code{background:rgba(94,75,138,.1);color:#5e4b8a}
.plan-content strong{color:#4338ca}
details.tool-loop{margin:.8rem 0 .8rem 1.5rem;border:1px solid #e0e4e8;border-radius:10px;background:#f8fafc}
details.tool-loop>summary{padding:.6rem 1rem;cursor:pointer;font-weight:600;font-size:.88rem;
  list-style:none;display:flex;align-items:center;gap:.5rem;color:#4b5563;border-radius:10px}
details.tool-loop>summary::-webkit-details-marker{display:none}
details.tool-loop>summary .tool-loop-icons{font-size:1.1em}
details.tool-loop>summary .tool-loop-label{flex:1}
details.tool-loop>summary .tool-loop-chevron{margin-left:auto;transition:transform .2s;color:#888;font-size:.7em}
details.tool-loop[open]>summary .tool-loop-chevron{transform:rotate(90deg)}
details.tool-loop[open]>summary{border-bottom:1px solid #e0e4e8;border-radius:10px 10px 0 0}
.tool-loop-body{padding:.5rem}
.tool-loop-body details.tool{margin-left:.5rem}
.system-notice{background:#fef3c7;border-left:4px solid #d97706;padding:.75rem 1rem;
  border-radius:0 8px 8px 0;margin:1.2rem 0;font-size:.85rem;color:#92400e}
.system-notice .label{font-weight:700;color:#d97706;font-size:.75rem;text-transform:uppercase;
  letter-spacing:.5px;margin-bottom:.25rem}
.thinking{background:#f8f9fa;border-left:3px solid #9ca3af;padding:.5rem 1rem;
  margin:.5rem 0 .5rem 1.5rem;border-radius:0 6px 6px 0;color:#6b7280;font-size:.9rem;font-style:italic}
.thinking em{font-style:italic}
"""

_SPINNER_STYLE = (
    "<style>.bz-spin-box{display:flex;align-items:center;gap:8px;margin:1rem 0;padding:.5rem}"
    ".bz-spin{width:20px;height:20px;border:3px solid #eee;border-top-color:#3498db;"
    "border-radius:50%;animation:bz-spin .8s linear infinite}"
    "@keyframes bz-spin{to{transform:rotate(360deg)}}</style>"
)
_SPINNER_HTML = (
    _SPINNER_STYLE
    + '<div class="bz-spin-box"><div class="bz-spin"></div>'
    + "<span>Session en cours&#8230;</span></div>"
)

_MONACO_CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min"
_MONACO_INIT_SCRIPT = (
    f'<script src="{_MONACO_CDN}/vs/loader.js"></script>\n'
    "<script>\n"
    "if(window.__bz_diffs&&window.__bz_diffs.length){\n"
    f"  require.config({{paths:{{vs:'{_MONACO_CDN}/vs'}}}});\n"
    "  require(['vs/editor/editor.main'],function(){\n"
    "    var map={};\n"
    "    window.__bz_diffs.forEach(function(d){map[d.id]=d});\n"
    "    function initDiff(el,d){\n"
    "      el.querySelector('.diff-fallback').remove();\n"
    "      var ed=monaco.editor.createDiffEditor(el,{\n"
    "        readOnly:true,renderSideBySide:true,\n"
    "        minimap:{enabled:false},scrollBeyondLastLine:false,\n"
    "        automaticLayout:true,fontSize:13,lineNumbers:'off'\n"
    "      });\n"
    "      ed.setModel({\n"
    "        original:monaco.editor.createModel(d.original,d.lang),\n"
    "        modified:monaco.editor.createModel(d.modified,d.lang)\n"
    "      });\n"
    "    }\n"
    "    var obs=new IntersectionObserver(function(entries){\n"
    "      entries.forEach(function(e){\n"
    "        if(!e.isIntersecting)return;\n"
    "        var d=map[e.target.id];\n"
    "        if(d&&!d.done){d.done=true;obs.unobserve(e.target);initDiff(e.target,d);}\n"
    "      });\n"
    "    },{threshold:0.01});\n"
    "    window.__bz_diffs.forEach(function(d){\n"
    "      var el=document.getElementById(d.id);\n"
    "      if(el)obs.observe(el);\n"
    "    });\n"
    "  });\n"
    "}\n"
    "</script>"
)


# ── Markdown helpers ────────────────────────────────────────────────
def _md_table(lines: list[str]) -> str:
    """Convert a block of pipe-delimited markdown lines to an HTML table."""
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip().strip("|")
        cells = [c.strip() for c in stripped.split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return "<p>" + html.escape(" ".join(lines)) + "</p>"
    # Row 1 = header, row 2 = separator (skip), rest = body
    header = rows[0]
    body_start = 2 if re.match(r"^[\s|:-]+$", lines[1].strip()) else 1
    body = rows[body_start:]
    def _cell_html(cell: str) -> str:
        escaped = html.escape(cell)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        return escaped
    th = "".join(f"<th>{_cell_html(c)}</th>" for c in header)
    tr_body = "".join(
        "<tr>" + "".join(f"<td>{_cell_html(c)}</td>" for c in row) + "</tr>"
        for row in body
    )
    return f'<table class="md-table"><thead><tr>{th}</tr></thead><tbody>{tr_body}</tbody></table>'


def _md(text: str) -> str:
    """Minimal markdown to HTML: headings, bold, code, code blocks, lists, tables."""
    parts = re.split(r"```(\w*)\n?(.*?)```", text, flags=re.DOTALL)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 3 == 1:
            continue  # language tag
        if i % 3 == 2:
            out.append(f"<pre><code>{html.escape(part.strip())}</code></pre>")
            continue
        # Group consecutive table lines (starting with |) before per-line processing
        processed: list[str] = []
        table_buf: list[str] = []
        for raw_line in part.split("\n"):
            if re.match(r"^\s*\|.+\|", raw_line):
                table_buf.append(raw_line)
                continue
            if table_buf:
                processed.append(_md_table(table_buf))
                table_buf = []
            # Normal line processing
            hm = re.match(r"^(#{1,3})\s+(.+)$", raw_line)
            if hm:
                lvl = len(hm.group(1))
                processed.append(f"<h{lvl}>{html.escape(hm.group(2))}</h{lvl}>")
                continue
            escaped = html.escape(raw_line)
            escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
            escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            bm = re.match(r"^(\s*)[-*]\s+(.+)$", escaped)
            if bm:
                processed.append(f"<li>{bm.group(2)}</li>")
                continue
            processed.append(escaped)
        if table_buf:
            processed.append(_md_table(table_buf))
        joined = "\n".join(processed)
        # Wrap consecutive <li> in <ul>
        joined = re.sub(
            r"((?:<li>.*?</li>\n?)+)",
            lambda m: f"<ul>{m.group(1)}</ul>",
            joined,
        )
        for paragraph in re.split(r"\n{2,}", joined):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if paragraph.startswith(("<h", "<ul", "<pre", "<table")):
                out.append(paragraph)
            else:
                out.append(f"<p>{paragraph}</p>")
    return "\n".join(out)


# ── Diff rendering ──────────────────────────────────────────────────
def _render_diff_text(old: str, new: str) -> str:
    """Simple text-based unified diff (used as fallback inside Monaco container)."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after")
    spans: list[str] = []
    for d in diff:
        d = d.rstrip("\n")
        escaped = html.escape(d)
        if d.startswith("+++") or d.startswith("---") or d.startswith("@@"):
            cls = "diff-hdr"
        elif d.startswith("+"):
            cls = "diff-add"
        elif d.startswith("-"):
            cls = "diff-del"
        else:
            cls = ""
        attr = f' class="diff-line {cls}"' if cls else ' class="diff-line"'
        spans.append(f"<span{attr}>{escaped}</span>")
    return f'<div class="diff">{"".join(spans)}</div>' if spans else ""


def _render_diff(old: str, new: str, file_path: str = "", call_id: str = "0") -> str:
    """Monaco diff container with a text-diff fallback inside."""
    cid = f"bz-diff-{html.escape(call_id)}"
    lang = _guess_language(file_path)
    n_lines = max(old.count("\n"), new.count("\n")) + 1
    height = min(500, max(100, n_lines * 22 + 40))
    fallback = _render_diff_text(old, new)
    return (
        f'<div id="{cid}" class="monaco-diff-box" style="height:{height}px">'
        f'<div class="diff-fallback">{fallback}</div>'
        f"</div>\n"
        f"<script>window.__bz_diffs=window.__bz_diffs||[];"
        f"window.__bz_diffs.push({{id:{_json_script_safe(cid)},"
        f"lang:{_json_script_safe(lang)},"
        f"original:{_json_script_safe(old)},"
        f"modified:{_json_script_safe(new)}}});</script>"
    )


# ── Param rendering ─────────────────────────────────────────────────
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


# ── Result rendering ────────────────────────────────────────────────
def _format_result(result: ToolResult) -> str:
    content = result.content
    if len(content) > 8000:
        content = content[:8000] + f"\n... ({len(result.content)} chars total)"
    if result.tool_name in ("Bash", "RunPythonTest"):
        formatted = clean_stdout(content)
    else:
        formatted = html.escape(content)
    return f'<div class="result-section"><div class="result-label">Result</div><pre>{formatted}</pre></div>'


# ── Block rendering ─────────────────────────────────────────────────
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


_CTX_BAR_CSS = """\
.ctx-bar{margin:12px 0;border:1px solid #e0e0e0;border-radius:6px;background:#f8f9fa;font-family:system-ui,sans-serif;font-size:13px}
.ctx-bar summary{padding:8px 14px;cursor:pointer;color:#555;display:flex;align-items:center;gap:10px;list-style:none}
.ctx-bar summary::-webkit-details-marker{display:none}
.ctx-bar summary::before{content:'\\25B6';font-size:10px;transition:transform .2s}
.ctx-bar[open] summary::before{transform:rotate(90deg)}
.ctx-bar summary:hover{background:#eef}
.ctx-bar .ctx-tokens{font-weight:600;color:#333}
.ctx-badge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px}
.ctx-badge-live{background:#d4edda;color:#155724}
.ctx-badge-trashed{background:#f8d7da;color:#721c24}
.ctx-badge-notes{background:#cce5ff;color:#004085}
.ctx-table{width:100%;border-collapse:collapse}
.ctx-table th{text-align:left;padding:4px 10px;background:#e9ecef;font-size:11px;text-transform:uppercase;color:#666;border-bottom:1px solid #dee2e6}
.ctx-table td{padding:4px 10px;border-bottom:1px solid #f0f0f0;font-size:12px}
.ctx-table .ctx-type{width:90px}
.ctx-table .ctx-tok{width:70px;text-align:right;font-variant-numeric:tabular-nums}
.ctx-table .ctx-st{width:70px}
.ctx-row-trashed td{color:#999;text-decoration:line-through}
.ctx-row-snippet td{color:#856404}
.ctx-row-compacted td{color:#6c757d;font-style:italic}
.ctx-row-cached td{color:#004085}
.ctx-s-live{background:#d4edda;color:#155724}
.ctx-s-trashed{background:#f8d7da;color:#721c24}
.ctx-s-snippet{background:#fff3cd;color:#856404}
.ctx-s-cached{background:#cce5ff;color:#004085}
.ctx-s-compacted{background:#e2e3e5;color:#383d41}
.ctx-pill{display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px}
"""


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
