# [desc] Renders parsed session blocks into self-contained HTML with rich tool display, diffs, and markdown. [/desc]
# [desc] Renders parsed session blocks into self-contained HTML with rich tool display, diffs, and markdown.
"""Render parsed session blocks to a self-contained HTML page."""
import difflib
import html
import json
import os
import re

from .parser import AssistantText, Block, ToolCall, ToolResult, UserMessage

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
def _md(text: str) -> str:
    """Minimal markdown to HTML: headings, bold, code, code blocks, lists."""
    parts = re.split(r"```(\w*)\n?(.*?)```", text, flags=re.DOTALL)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 3 == 1:
            continue  # language tag
        if i % 3 == 2:
            out.append(f"<pre><code>{html.escape(part.strip())}</code></pre>")
            continue
        lines: list[str] = []
        for line in part.split("\n"):
            hm = re.match(r"^(#{1,3})\s+(.+)$", line)
            if hm:
                lvl = len(hm.group(1))
                lines.append(f"<h{lvl}>{html.escape(hm.group(2))}</h{lvl}>")
                continue
            escaped = html.escape(line)
            escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
            escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            bm = re.match(r"^(\s*)[-*]\s+(.+)$", escaped)
            if bm:
                lines.append(f"<li>{bm.group(2)}</li>")
                continue
            lines.append(escaped)
        joined = "\n".join(lines)
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
            if paragraph.startswith(("<h", "<ul", "<pre")):
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
    return f'<div class="result-section"><div class="result-label">Result</div><pre>{html.escape(content)}</pre></div>'


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
    in_tok = meta.get("total_input_tokens", 0) or 0
    out_tok = meta.get("total_output_tokens", 0) or 0
    cache_r = meta.get("total_cache_read_tokens", 0) or 0
    cache_c = meta.get("total_cache_creation_tokens", 0) or 0
    total = in_tok + out_tok + cache_r + cache_c
    if total == 0:
        return ""
    cost = (in_tok * 15.0 + cache_r * 1.5 + cache_c * 18.75 + out_tok * 5.0) / 1_000_000
    return (
        f'<div class="session-footer">'
        f'{_fmt_tok(in_tok)} input &middot; {_fmt_tok(out_tok)} output'
        f' &middot; {_fmt_tok(cache_r)} cache read &middot; {_fmt_tok(cache_c)} cache write'
        f' &middot; <strong>{_fmt_tok(total)} total</strong>'
        f' &middot; est. <strong>${cost:.2f}</strong>'
        f'</div>'
    )


def render_html(blocks: list[Block], finished: bool = True, meta: dict | None = None) -> str:
    """Render parsed blocks to a complete self-contained HTML string."""
    head = (
        '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="utf-8">'
        f'<title>Bouzecode Session</title>\n<style>\n{_CSS}\n</style></head>\n<body>\n'
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

    consumed_results: set[int] = set()
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if isinstance(block, UserMessage):
            parts.append(
                f'<div class="user-msg"><div class="label">You</div>'
                f'{_md(block.content)}</div>'
            )
        elif isinstance(block, AssistantText):
            parts.append(f'<div class="assistant">{_md(block.content)}</div>')
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

    if not finished:
        parts.append(_SPINNER_HTML)

    if finished and meta:
        parts.append(_render_session_footer(meta))

    if any("monaco-diff-box" in p for p in parts):
        parts.append(_MONACO_INIT_SCRIPT)

    parts.append("\n</body>\n</html>")
    return "\n".join(parts)
