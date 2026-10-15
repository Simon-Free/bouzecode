"""Rendu du corps d'un item de contexte : markdown formate + XML togglable.

Le texte d'un tour melange de la prose markdown et des blocs XML de tool
calls. On separe les deux : la prose passe par le mini-markdown maison,
chaque bloc XML devient un <details> replie contenant du XML indente.
"""
from __future__ import annotations

import re
from html import escape

from bouzecode.web_v2.services.message_render_helpers import render_markdown

_XML_BLOCK_RE = re.compile(r"<(tool_calls|tool_use|thinking)\b[^>]*>.*?</\1>", re.S)
_CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]" + ">", re.S)
_TAG_RE = re.compile(r"(<[^>]+>)")


def render_body_html(text: str) -> str:
    """Prose -> markdown HTML, blocs XML -> <details> indentes."""
    if not text:
        return ""
    out: list[str] = []
    pos = 0
    for match in _XML_BLOCK_RE.finditer(text):
        prose = text[pos : match.start()]
        if prose.strip():
            out.append(render_markdown(prose))
        out.append(_render_xml_block(match.group(0)))
        pos = match.end()
    tail = text[pos:]
    if tail.strip():
        out.append(render_markdown(tail))
    return "".join(out)


def _root_label(raw: str) -> str:
    opening = re.match(r"<(\w+)([^>]*)>", raw)
    if not opening:
        return "XML"
    attrs = opening.group(2) or ""
    named = re.search(r'name="([^"]+)"', attrs)
    return f"{opening.group(1)} {named.group(1)}" if named else opening.group(1)


def _render_xml_block(raw: str) -> str:
    return (
        '<details class="cd-xml"><summary>'
        f'<span class="cd-xml-tag">XML</span> {escape(_root_label(raw))}'
        "</summary>"
        f"<pre><code>{escape(indent_xml(raw))}</code></pre>"
        "</details>"
    )


def indent_xml(raw: str) -> str:
    """Indentation naive et tolerante (jamais de parseur strict)."""
    holes: list[str] = []

    def _stash(match: re.Match) -> str:
        holes.append(match.group(0))
        return f"\x00{len(holes) - 1}\x00"

    body = _CDATA_RE.sub(_stash, raw)
    lines: list[str] = []
    depth = 0
    for token in _TAG_RE.split(body):
        if not token or not token.strip():
            continue
        if token.startswith("</"):
            depth = max(depth - 1, 0)
            lines.append("  " * depth + token)
        elif token.startswith("<?") or token.startswith("<!"):
            lines.append("  " * depth + token)
        elif token.startswith("<"):
            lines.append("  " * depth + token)
            if not token.endswith("/>"):
                depth += 1
        else:
            lines.append("  " * depth + token.strip())
    out = "\n".join(lines)
    for index, hole in enumerate(holes):
        out = out.replace(f"\x00{index}\x00", hole)
    return out
