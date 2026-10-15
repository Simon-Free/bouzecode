# [desc] Minimal markdown-to-HTML converter (headings, bold, code, lists, tables) for the session renderer. [/desc]
"""Minimal markdown → HTML conversion helpers for the session renderer."""
import html
import re


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


def _md_line(raw_line: str) -> str:
    """Une ligne hors tableau : titre, puce ou texte (gras et code inline)."""
    hm = re.match(r"^(#{1,3})\s+(.+)$", raw_line)
    if hm:
        lvl = len(hm.group(1))
        return f"<h{lvl}>{html.escape(hm.group(2))}</h{lvl}>"
    escaped = html.escape(raw_line)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    bm = re.match(r"^(\s*)[-*]\s+(.+)$", escaped)
    return f"<li>{bm.group(2)}</li>" if bm else escaped


def _md_lines(part: str) -> list[str]:
    """Les lignes d'un segment hors bloc de code, les lignes de tableau consécutives groupées."""
    processed: list[str] = []
    table_buf: list[str] = []
    for raw_line in part.split("\n"):
        if re.match(r"^\s*\|.+\|", raw_line):
            table_buf.append(raw_line)
            continue
        if table_buf:
            processed.append(_md_table(table_buf))
            table_buf = []
        processed.append(_md_line(raw_line))
    if table_buf:
        processed.append(_md_table(table_buf))
    return processed


def _md_prose(part: str) -> list[str]:
    """Paragraphes HTML d'un segment hors bloc de code (puces consécutives → <ul>)."""
    joined = re.sub(r"((?:<li>.*?</li>\n?)+)", lambda m: f"<ul>{m.group(1)}</ul>",
                    "\n".join(_md_lines(part)))
    paragraphs = (p.strip() for p in re.split(r"\n{2,}", joined))
    return [p if p.startswith(("<h", "<ul", "<pre", "<table")) else f"<p>{p}</p>"
            for p in paragraphs if p]


def _md(text: str) -> str:
    """Minimal markdown to HTML: headings, bold, code, code blocks, lists, tables."""
    # re.split avec 2 groupes : [prose, langage, code, prose, langage, code, …]
    parts = re.split(r"```(\w*)\n?(.*?)```", text, flags=re.DOTALL)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 3 == 2:
            out.append(f"<pre><code>{html.escape(part.strip())}</code></pre>")
        elif i % 3 == 0:
            out.extend(_md_prose(part))
    return "\n".join(out)
