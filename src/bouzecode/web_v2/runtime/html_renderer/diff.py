# [desc] Session renderer diff rendering: unified text diff fallback plus Monaco diff container. [/desc]
"""Diff rendering (text fallback + Monaco container) for the session renderer."""
import difflib
import html

from .markdown import _guess_language, _json_script_safe


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
