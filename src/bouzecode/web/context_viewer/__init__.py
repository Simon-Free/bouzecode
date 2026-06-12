# [desc] Package entry point: public API for the per-LLM-call context viewer (HTML page + inline session-page stats). [/desc]
"""Public API for the BouzéqUI context viewer."""
import html
import json

from ...web.context_viewer.builder import extract_per_call_data


def build_turn_breakdowns(session_path: str) -> dict[int, dict] | None:
    """Per-turn summary used by the inline session-page stats bar."""
    data = extract_per_call_data(session_path)
    if data is None:
        return None
    out: dict[int, dict] = {}
    for call in data["calls"]:
        items = call["items"]
        n_trashed = sum(1 for it in items if it.get("gc_status") == "trashed")
        n_live = sum(1 for it in items if it.get("gc_status") in ("live", "verbatim", "stable"))
        n_notes = sum(1 for it in items if it["kind"] == "notes_block")
        total = sum(it["est_tokens"] for it in items)
        out[call["turn"]] = {
            "total_tokens": total, "n_items": len(items),
            "n_trashed": n_trashed, "n_live": n_live, "n_notes": n_notes,
            "items": [
                {"type": it["kind"], "label": it["label"],
                 "tokens": it["est_tokens"], "status": it.get("gc_status", "live")}
                for it in items
            ],
        }
    return out


def render_context_viewer(session_path: str) -> str | None:
    data = extract_per_call_data(session_path)
    if data is None:
        return None
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    session_id = html.escape(data["session_id"])
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        f'<title>Context Viewer - {session_id}</title>'
        '<link rel="stylesheet" href="/static/context_viewer.css">'
        '</head><body>'
        f'<script>window.__CTX={data_json};</script>'
        '<div id="app"></div>'
        '<script src="/static/context_viewer.js"></script>'
        '</body></html>'
    )


__all__ = ["build_turn_breakdowns", "render_context_viewer", "extract_per_call_data"]
