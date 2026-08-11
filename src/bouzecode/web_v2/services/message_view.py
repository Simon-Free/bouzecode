# [desc] Transforme chaque message JSON de session en bloc HTML autonome (rendu serveur, tout échappé). [/desc]
"""Rendu serveur des messages.

Tout texte est échappé via html.escape AVANT toute mise en forme (mini-markdown
maison) : aucun contenu de session ne peut casser la page — contrairement au
parsing de stdout streamé de la v1.

BILINGUE SANS SERVEUR BILINGUE. Le chrome de ces blocs porte un attribut `data-i18n` et son
texte ANGLAIS, langue par défaut : le serveur ne négocie rien, le client réécrit s'il affiche
le français (cf. static/js/i18n/README.md).

RÈGLE À NE PAS ENFREINDRE : `data-i18n` ne se pose que sur un élément FEUILLE. `applyDom`
écrit `textContent` et effacerait les enfants — dont le `<span class="event-time">` que le
front hydrate. D'où les `<span>` dédiés autour des seuls mots traduisibles.
"""
from __future__ import annotations

import html
import json
import re

from .message_render_helpers import (
    INPUT_SUMMARY_KEYS,
    MARKDOWN_CONTENT_TOOLS,
    MAX_INPUT_CHARS,
    MAX_RESULT_CHARS,
    MAX_USER_CHARS,
    SUBAGENT_TOOLS,
    _content_text,
    _render_thinking,
    _strip_thinking,
    _truncate,
    render_markdown,
)

__all__ = [
    "render_message",
    "render_markdown",
    "_content_text",
    "_render_thinking",
    "_strip_thinking",
    "_truncate",
    "INPUT_SUMMARY_KEYS",
    "MARKDOWN_CONTENT_TOOLS",
    "MAX_INPUT_CHARS",
    "MAX_RESULT_CHARS",
    "MAX_USER_CHARS",
    "SUBAGENT_TOOLS",
]


def render_message(message: dict, context_url: str | None = None) -> str:
    role = message.get("role", "")
    if role == "user":
        text = _truncate(_content_text(message), MAX_USER_CHARS)
        return f'<div class="block user pui-bubble pui-bubble--user">{render_markdown(text)}</div>'
    if role == "assistant":
        return _assistant_block(message, context_url)
    if role == "tool":
        return _tool_result_block(message)
    if role == "subagent_event":
        return _subagent_event_block(message)
    if role == "enforcement":
        return _enforcement_block(message)
    text = html.escape(_content_text(message)[:500])
    return f'<div class="block notice"><div class="role">{html.escape(role)}</div><p>{text}</p></div>'


def _assistant_block(message: dict, context_url: str | None = None) -> str:
    parts = ['<div class="block assistant pui-bubble pui-bubble--ai">']
    if context_url is not None:
        # Lien « ? » : ouvre le diagnostic du contexte injecté à ce tour dans un
        # nouvel onglet (GET .../turns/<n>/context). Design serveur-side : marche
        # sur toutes les pages (/conversations incluse) sans handler JS.
        parts.append(
            f'<a class="turn-context-help" href="{html.escape(context_url)}" '
            f'target="_blank" rel="noopener" data-i18n-title="block.context_help" '
            f'title="What context this turn sent to the model '
            f'(cache status and the turn each item was added on)">?</a>'
        )
    text = _content_text(message)
    thinking_html = _render_thinking(text)
    if thinking_html:
        parts.append(thinking_html)
    visible = _strip_thinking(text)
    if visible:
        parts.append(render_markdown(visible))
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        n = len(tool_calls)
        key = "block.tool_count_one" if n == 1 else "block.tool_count_many"
        label = f"{n} tool" if n == 1 else f"{n} tools"
        parts.append(
            f'<details class="tools-group">'
            f'<summary data-i18n="{key}" data-i18n-arg-count="{n}">{label}</summary>'
        )
        for tool_call in tool_calls:
            parts.append(_tool_call_html(tool_call))
        parts.append("</details>")
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
        body = f'<pre class="code code-block">{html.escape(_truncate(pretty, MAX_INPUT_CHARS))}</pre>'
    is_subagent = css_class == "subagent"
    kind_key = "block.kind_subagent" if is_subagent else "block.kind_tool"
    label = "subagent" if is_subagent else "tool"
    tool_id = tool_call.get("id")
    id_attr = f' data-tool-id="{html.escape(str(tool_id))}"' if tool_id else ""
    return (
        f'<details class="tc {css_class} pui-tool-panel"{id_attr}><summary>'
        f'<span class="tc-kind" data-i18n="{kind_key}">{label}</span> <span class="pui-dot"></span> '
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


def _enforcement_block(message: dict) -> str:
    """Bloc persistant traçant un enforcement (recovery Methodology/Snippet).
    Persisté dans session.json sous role="enforcement" (jamais role="user") pour
    permettre le débug depuis web_v2. Rendu en ligne fine, style warning."""
    tools = message.get("missing_tools") or []
    if tools:
        label = ", ".join(html.escape(str(t)) for t in tools)
        body = f"⚠️ Enforcement: requesting {label}…"
    else:
        body = html.escape(_content_text(message)[:500]) or "⚠️ Enforcement"
    return (
        f'<div class="block enforcement">'
        f'<span class="subagent-event-line">{body}</span></div>'
    )


def _subagent_event_block(message: dict) -> str:
    """Fine ligne séparatrice inline traçant le lancement / la complétion des sous-agents.
    Cliquable (data-open-key) → le front ouvre l'onglet du sous-agent. Un lancement
    multiple (count>1) est dépliable pour cibler chaque sous-agent individuellement."""
    agents = message.get("agents") or []
    if not agents:
        return ""
    subtype = message.get("subtype", "launch")
    count = int(message.get("count", len(agents)))
    if subtype == "done":
        a = agents[0]
        verdict = a.get("verdict") or ""
        suffix = (
            f' <span data-i18n="block.verdict" data-i18n-arg-verdict="{html.escape(verdict)}">'
            f'— verdict {html.escape(verdict)}</span>'
        ) if verdict else ""
        label = html.escape(a.get("label", ""))
        return (
            f'<div class="block subagent-event subagent-event--done" '
            f'data-open-key="{html.escape(a.get("open_key", ""))}">'
            f'<span class="subagent-event-line">✅ {label}{_event_time(a)} '
            f'<span data-i18n="block.subagent_done">done</span>{suffix}</span></div>'
        )
    # launch
    if count > 1:
        items = "".join(
            f'<button type="button" class="subagent-event-child" '
            f'data-open-key="{html.escape(a.get("open_key", ""))}">'
            f'{html.escape(a.get("label", ""))}{_event_time(a)}</button>'
            for a in agents
        )
        return (
            f'<details class="block subagent-event subagent-event--group">'
            f'<summary class="subagent-event-line" data-i18n="block.subagents_launched" '
            f'data-i18n-arg-count="{count}">🤖 {count} agents launched</summary>'
            f'<div class="subagent-event-children">{items}</div></details>'
        )
    a = agents[0]
    label = html.escape(a.get("label", ""))
    return (
        f'<div class="block subagent-event" '
        f'data-open-key="{html.escape(a.get("open_key", ""))}">'
        f'<span class="subagent-event-line">🤖 '
        f'<span data-i18n="block.subagent_launched">1 agent launched</span> — '
        f'{label}{_event_time(a)}</span></div>'
    )


def _event_time(a: dict) -> str:
    """Span vide horodaté, hydraté côté front (heure LOCALE) depuis `started_at`
    (ISO UTC). L'heure n'est JAMAIS cuite serveur-side : formatEventTime() la remplit."""
    iso = a.get("started_at") or ""
    if not iso:
        return ""
    return f' <span class="event-time" data-iso="{html.escape(iso)}"></span>'


def _tool_result_block(message: dict) -> str:
    name = str(message.get("name", ""))
    content = _content_text(message)
    kind = _final_answer_kind(name, content)
    if kind == "final_answer":
        # Extract the answer text after the prefix line
        answer_text = content.split("\n", 1)[1] if "\n" in content else content
        return (
            f'<div class="block final-answer">'
            f'<div class="role pui-eyebrow" data-i18n="block.final_answer">✅ Final answer</div>'
            f'{render_markdown(answer_text)}</div>'
        )
    if kind == "final_answer_refused":
        return (
            f'<div class="block final-answer-refused">'
            f'<div class="role pui-eyebrow" data-i18n="block.closure_refused">'
            f'❌ Closure refused by the validator</div>'
            f'{render_markdown(content)}</div>'
        )
    is_error = bool(re.match(r"\s*(Error|Erreur|Traceback|BLOCKED)", content))
    css_class = " error" if is_error else ""
    # Le nombre de caractères est GROUPÉ ici (« 12 480 ») : c'est un format de nombre, pas un
    # libellé, et le refaire côté client demanderait un formateur pour rien.
    size = f"{len(content):,}".replace(",", " ")
    header = f"{name} result — {size} chars"
    call_id = message.get("tool_call_id")
    id_attr = f' data-tool-call-id="{html.escape(str(call_id))}"' if call_id else ""
    return (
        f'<details class="tr{css_class} pui-tool-panel"{id_attr}><summary>'
        f'<span class="pui-dot"></span> '
        f'<span data-i18n="block.tool_result" data-i18n-arg-name="{html.escape(name)}" '
        f'data-i18n-arg-size="{size}">{html.escape(header)}</span></summary>'
        f'<pre class="code code-block">{html.escape(_truncate(content, MAX_RESULT_CHARS))}</pre></details>'
    )
