"""Render a per-turn context diagnostic as readable HTML (not raw JSON).

Each element is a togglable <details> block whose summary shows the element
kind, its cache status (cache read / cache write / fresh) and the turn at which
it first entered the context.
"""
from __future__ import annotations

from html import escape

_STATUS_CLASS = {
    "cache read": "st-cached",
    "cache write": "st-write",
    "fresh": "st-fresh",
}

_KIND_LABEL = {
    "system": "System prompt",
    "notes_block": "Methodology (notes)",
    "user": "User",
    "assistant": "Assistant",
    "tool_result": "Tool result",
}

_CSS = """
<style>
.cd-wrap{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:1000px;margin:1rem auto;color:#e6e6e6;background:#1e1e1e;padding:1rem;}
.cd-wrap h1{font-size:1.15rem;margin:0 0 .3rem;}
.cd-meta{font-size:.8rem;color:#9aa;margin-bottom:1rem;}
.cd-sec{margin:1.2rem 0;}
.cd-sec>h2{font-size:1rem;border-bottom:1px solid #444;padding-bottom:.2rem;}
.cd-item{border:1px solid #333;border-radius:5px;margin:.4rem 0;background:#252526;}
.cd-item>summary{cursor:pointer;padding:.4rem .6rem;list-style:none;display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;}
.cd-item>summary::-webkit-details-marker{display:none;}
.cd-kind{font-weight:600;}
.cd-badge{font-size:.7rem;padding:.1rem .45rem;border-radius:999px;text-transform:uppercase;letter-spacing:.03em;}
.st-cached{background:#3a3a3a;color:#bbb;}
.st-write{background:#1c3a5e;color:#7fbfff;}
.st-fresh{background:#1c4d2b;color:#7fe0a0;}
.cd-turn{font-size:.72rem;color:#c9a227;}
.cd-tok{font-size:.72rem;color:#888;margin-left:auto;}
.cd-body{padding:.5rem .7rem;border-top:1px solid #333;}
.cd-body pre{white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,Consolas,monospace;font-size:.78rem;margin:0;color:#d4d4d4;}
.cd-turn-group{font-size:.85rem;color:#c9a227;margin:.9rem 0 .3rem;border-bottom:1px dashed #444;padding-bottom:.15rem;}
.cd-turn-count{color:#888;font-weight:400;}
.cd-notes{font-size:.85rem;}
.cd-notes .tag{display:inline-block;padding:.05rem .4rem;border-radius:4px;margin:.1rem;}
.tag-add{background:#1c4d2b;color:#7fe0a0;}
.tag-upd{background:#1c3a5e;color:#7fbfff;}
.tag-rem{background:#5e1c1c;color:#ff9f9f;}
</style>
"""


def _render_item(item: dict) -> str:
    kind = item.get("kind", "")
    status = item.get("status_label", "fresh")
    cls = _STATUS_CLASS.get(status, "st-fresh")
    added = item.get("added_at_turn")
    added_txt = f"ajouté au tour {added}" if added is not None else "tour ?"
    label = item.get("label") or _KIND_LABEL.get(kind, kind)
    toks = item.get("est_tokens", 0)
    body = escape(item.get("text") or item.get("preview") or "")
    return (
        '<details class="cd-item">'
        "<summary>"
        f'<span class="cd-kind">{escape(_KIND_LABEL.get(kind, kind))}</span>'
        f'<span class="cd-badge {cls}">{escape(status)}</span>'
        f'<span class="cd-turn">{escape(added_txt)}</span>'
        f'<span class="cd-tok">~{toks} tok</span>'
        "</summary>"
        f'<div class="cd-body"><div style="font-size:.78rem;color:#9aa;margin-bottom:.3rem">'
        f"{escape(label)}</div><pre>{body}</pre></div>"
        "</details>"
    )


def _render_notes_delta(nd: dict | None) -> str:
    if not nd:
        return ""
    parts = []
    for key, cls, lbl in (("added", "tag-add", "+"), ("updated", "tag-upd", "~"),
                          ("removed", "tag-rem", "-")):
        for name in nd.get(key, []) or []:
            parts.append(f'<span class="tag {cls}">{lbl} {escape(str(name))}</span>')
    if not parts:
        return ""
    return (
        '<div class="cd-sec"><h2>Notes (méthodologie) — delta ce tour</h2>'
        f'<div class="cd-notes">{"".join(parts)}</div></div>'
    )


def _render_cached_grouped(cached: list[dict]) -> str:
    """Render cache-read items grouped by their origin turn (added_at_turn).

    Groups are ordered by ascending origin turn (chronological order of entry
    into the context/cache). Items without a known origin turn are collected in
    a trailing "tour ?" group.
    """
    if not cached:
        return "<em>Aucun élément caché.</em>"

    groups: dict[object, list[dict]] = {}
    for item in cached:
        added = item.get("added_at_turn")
        groups.setdefault(added, []).append(item)

    # Sort: known turns ascending first, unknown (None) last.
    def _sort_key(turn):
        return (1, 0) if turn is None else (0, turn)

    parts: list[str] = []
    for turn in sorted(groups, key=_sort_key):
        items = groups[turn]
        header = f"Tour {turn}" if turn is not None else "Tour ?"
        items_html = "".join(_render_item(i) for i in items)
        parts.append(
            f'<h3 class="cd-turn-group">{escape(header)} '
            f'<span class="cd-turn-count">({len(items)})</span></h3>'
            f"{items_html}"
        )
    return "".join(parts)


def render_context_diag_html(diag: dict | None) -> str:
    if not diag:
        return _CSS + '<div class="cd-wrap"><h1>Aucun diagnostic disponible pour ce tour.</h1></div>'

    t = diag.get("totals", {})
    delta = diag.get("delta_items", [])
    cached = diag.get("cached_items", [])

    head = (
        f'<div class="cd-wrap"><h1>Contexte envoyé au modèle — tour {escape(str(diag.get("turn")))}</h1>'
        f'<div class="cd-meta">session {escape(str(diag.get("session_id")))} · '
        f'{escape(str(diag.get("model")))} · {escape(str(diag.get("timestamp") or ""))}<br>'
        f'input {t.get("api_input_tokens", 0)} tok · output {t.get("api_output_tokens", 0)} · '
        f'cache read {t.get("api_cache_read", 0)} · cache write {t.get("api_cache_create", 0)} · '
        f'{t.get("wire_message_count", 0)} messages wire</div>'
    )

    delta_html = "".join(_render_item(i) for i in delta) or "<em>Aucun nouvel élément ce tour.</em>"
    cached_html = _render_cached_grouped(cached)

    sec_delta = (
        '<div class="cd-sec"><h2>Nouveau ce tour (delta ajouté au contexte — fresh / cache write)</h2>'
        f"{delta_html}</div>"
    )
    sec_notes = _render_notes_delta(diag.get("notes_delta"))
    sec_cached = (
        '<details class="cd-sec"><summary><h2 style="display:inline">Déjà en contexte (cache read)</h2></summary>'
        f"{cached_html}</details>"
    )

    return _CSS + head + sec_delta + sec_notes + sec_cached + "</div>"
