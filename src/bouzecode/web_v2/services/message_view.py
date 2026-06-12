# [desc] Transforme chaque message JSON de session en bloc HTML autonome (rendu serveur, tout échappé). [/desc]
"""Rendu serveur des messages.

Tout texte est échappé via html.escape AVANT toute mise en forme (mini-markdown
maison) : aucun contenu de session ne peut casser la page — contrairement au
parsing de stdout streamé de la v1.
"""
from __future__ import annotations

import html
import json
import re

SUBAGENT_TOOLS = {"agent", "task", "subagent", "spawn_agent"}
MARKDOWN_CONTENT_TOOLS = {"methodology", "writeplan", "write_plan", "todo_create"}
INPUT_SUMMARY_KEYS = ("file_path", "path", "command", "pattern", "prompt", "description", "content")
MAX_RESULT_CHARS = 4000
MAX_INPUT_CHARS = 2000
MAX_USER_CHARS = 6000

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.S)


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
            lines.append(f'<div class="li">• {re.sub(r"^\s*[-*]\s+", "", line)}</div>')
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


def render_message(message: dict) -> str:
    role = message.get("role", "")
    if role == "user":
        text = _truncate(_content_text(message), MAX_USER_CHARS)
        return f'<div class="block user"><div class="role">vous</div>{render_markdown(text)}</div>'
    if role == "assistant":
        return _assistant_block(message)
    if role == "tool":
        return _tool_result_block(message)
    text = html.escape(_content_text(message)[:500])
    return f'<div class="block notice"><div class="role">{html.escape(role)}</div><p>{text}</p></div>'


def _assistant_block(message: dict) -> str:
    parts = ['<div class="block assistant"><div class="role">assistant</div>']
    text = _content_text(message)
    if text.strip():
        parts.append(render_markdown(text))
    for tool_call in message.get("tool_calls") or []:
        parts.append(_tool_call_html(tool_call))
    parts.append("</div>")
    return "".join(parts)


def _input_summary(tool_input: dict) -> str:
    for key in INPUT_SUMMARY_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")[:110]
    return ""


def _tool_call_html(tool_call: dict) -> str:
    name = str(tool_call.get("name", "?"))
    tool_input = tool_call.get("input") if isinstance(tool_call.get("input"), dict) else {}
    css_class = "subagent" if name.lower() in SUBAGENT_TOOLS else "toolcall"
    if name.lower() in MARKDOWN_CONTENT_TOOLS and isinstance(tool_input.get("content"), str):
        body = render_markdown(tool_input["content"])
    else:
        pretty = json.dumps(tool_input, ensure_ascii=False, indent=2, default=str)
        body = f'<pre class="code">{html.escape(_truncate(pretty, MAX_INPUT_CHARS))}</pre>'
    label = "sous-agent" if css_class == "subagent" else "outil"
    return (
        f'<details class="tc {css_class}"><summary><span class="tc-kind">{label}</span> '
        f'<span class="tc-name">{html.escape(name)}</span> '
        f'<span class="tc-hint">{html.escape(_input_summary(tool_input))}</span></summary>'
        f"{body}</details>"
    )


def _final_answer_kind(name: str, content: str) -> str | None:
    """Detect FinalAnswer tool_result kind: 'final_answer', 'final_answer_refused', or None."""
    if name != "FinalAnswer":
        return None
    if content.startswith("CLÔTURE REFUSÉE"):
        return "final_answer_refused"
    if content.startswith("Session closing"):
        return "final_answer"
    return None


def _tool_result_block(message: dict) -> str:
    name = str(message.get("name", ""))
    content = _content_text(message)
    kind = _final_answer_kind(name, content)
    if kind == "final_answer":
        # Extract the answer text after the prefix line
        answer_text = content.split("\n", 1)[1] if "\n" in content else content
        return (
            f'<div class="block final-answer">'
            f'<div class="role">✅ Réponse finale</div>'
            f'{render_markdown(answer_text)}</div>'
        )
    if kind == "final_answer_refused":
        return (
            f'<div class="block final-answer-refused">'
            f'<div class="role">❌ Clôture refusée par le validateur</div>'
            f'{render_markdown(content)}</div>'
        )
    is_error = bool(re.match(r"\s*(Error|Erreur|Traceback|BLOCKED)", content))
    css_class = " error" if is_error else ""
    header = f"résultat {name} — {len(content):,} car.".replace(",", " ")
    return (
        f'<details class="tr{css_class}"><summary>{html.escape(header)}</summary>'
        f'<pre class="code">{html.escape(_truncate(content, MAX_RESULT_CHARS))}</pre></details>'
    )
