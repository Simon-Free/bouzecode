# [desc] Static constants (icons, colors, CSS, scripts, thinking regex) for the session HTML renderer. [/desc]
"""Static constants (icons, colors, CSS, scripts) for the session HTML renderer."""
import re

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
