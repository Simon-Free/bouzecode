# [desc] Minimal markdown-to-HTML converter (headings, bold, code, lists, tables) for the session renderer. [/desc]
"""Minimal markdown → HTML conversion helpers for the session renderer."""
import html
import json
import os
import re

from .constants import _LANG_MAP


def _guess_language(file_path: str) -> str:
    if not file_path:
        return "plaintext"
    return _LANG_MAP.get(os.path.splitext(file_path)[1].lower(), "plaintext")


def _json_script_safe(s: str) -> str:
    """JSON-encode a string, safe for embedding inside a &lt;script&gt; tag."""
    return json.dumps(s).replace("</", "<\\/")


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
