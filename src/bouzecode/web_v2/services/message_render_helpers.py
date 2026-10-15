# [desc] Helpers d'échappement et mini-markdown pour le rendu serveur des messages (thinking, prose, troncature).
# 
# <tool_use name="FinalAnswer" id="fa1"><param name="text">Helpers d'échappement et mini-markdown pour le rendu serveur des messages (thinking, prose, troncature).</param></tool_use> [/desc]
"""Helpers texte/markdown pour le rendu serveur des messages.

Extrait de message_view pour garder ce dernier sous 200 lignes. Tout texte est
echappe via html.escape AVANT toute mise en forme : aucun contenu de session ne
peut casser la page.
"""
from __future__ import annotations

import html
import re

from bouzecode.backend.agent.thinking_parser import normalize_orphan_close_tags

SUBAGENT_TOOLS = {"agent", "task", "subagent", "spawn_agent"}
MARKDOWN_CONTENT_TOOLS = {"methodology", "writeplan", "write_plan", "todo_create"}
INPUT_SUMMARY_KEYS = ("file_path", "path", "command", "pattern", "prompt", "description", "content")
MAX_RESULT_CHARS = 4000
MAX_INPUT_CHARS = 2000
MAX_USER_CHARS = 6000

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.S)

_THINKING_RE = re.compile(r"<thinking>\s*\n?(.*?)\n?\s*</thinking>", re.DOTALL)


def _render_thinking(content: str) -> str:
    """Extract <thinking> blocks and render them as italic muted HTML.

    Returns concatenated thinking HTML (empty if none). Content is escaped;
    newlines become <br>.
    """
    blocks = _THINKING_RE.findall(normalize_orphan_close_tags(content))
    if not blocks:
        return ""
    rendered = []
    for block in blocks:
        escaped = html.escape(block.strip()).replace("\n", "<br>")
        rendered.append(
            f'<details class="thinking pui-detail-thinking">'
            f'<summary class="pui-bubble__thinking-pill">réflexion</summary>'
            f'<em>{escaped}</em></details>'
        )
    return "".join(rendered)


def _methodology_html(tool_call: dict) -> str:
    """Le delta Methodology du tour, déplié hors du groupe d'outils : même pastille que
    la réflexion, contenu en markdown. L'appel reste aussi dans le groupe (appariement)."""
    tool_input = tool_call.get("input") if isinstance(tool_call.get("input"), dict) else {}
    content = tool_input.get("content")
    if not isinstance(content, str) or not content.strip():
        return ""
    return (
        '<details class="methodology pui-detail-thinking" open>'
        '<summary class="pui-bubble__thinking-pill">méthodologie</summary>'
        f'<div class="methodology-body">{render_markdown(content.strip())}</div></details>'
    )


def _strip_thinking(content: str) -> str:
    """Remove <thinking>...</thinking> blocks from content."""
    return _THINKING_RE.sub("", normalize_orphan_close_tags(content)).strip()


def render_markdown(text: str) -> str:
    """Mini-markdown sûr : blocs de code, titres, puces, gras, code inline."""
    parts = _FENCE_RE.split(text)
    rendered = []
    for i in range(0, len(parts), 3):
        rendered.append(_render_prose(parts[i]))
        if i + 2 < len(parts):
            rendered.append(f'<pre class="code"><code>{html.escape(parts[i + 2])}</code></pre>')
    return "".join(rendered)


def _render_prose(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", escaped)
    lines = []
    for line in escaped.split("\n"):
        heading = re.match(r"^(#{1,4})\s+(.*)", line)
        if heading:
            level = min(len(heading.group(1)) + 2, 6)
            lines.append(f"<h{level}>{heading.group(2)}</h{level}>")
        elif re.match(r"^\s*[-*]\s+", line):
            item = re.sub(r"^\s*[-*]\s+", "", line)
            lines.append(f'<div class="li">• {item}</div>')
        elif line.strip():
            lines.append(f"<p>{line}</p>")
    return "".join(lines)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (+{len(text) - limit} caractères tronqués)"


def _content_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return "" if content is None else str(content)
