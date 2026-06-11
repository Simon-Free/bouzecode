# [desc] Analyse par appel LLM: durées, tokens, cache hit, coût + drill-down payload annoté. [/desc]
"""Réutilise web.context_viewer (v1) : dumps exacts de payload + annotation cache.

`turn_table` répond à « où l'agent a perdu du temps » ; `turn_detail` répond à
« que contenait exactement ce tour, qu'est-ce qui était caché ou non ».
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ....backend.agent.providers.registry import calc_cost
from ....web.context_viewer.builder import extract_per_call_data
from .. import message_view
from . import store

CACHE_STATUS_LABELS = {"cached": "caché", "new-cache": "écrit au cache", "fresh": "plein tarif"}


def _hhmmss(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _cache_hit_pct(call: dict) -> int:
    denominator = call["api_input_tokens"]
    return round(100 * call["api_cache_read"] / denominator) if denominator else 0


def turn_table(session_path: str) -> dict | None:
    """Tableau des appels LLM. Δ = temps depuis l'appel précédent (LLM + outils)."""
    data = extract_per_call_data(session_path)
    if data is None:
        return None
    rows = []
    previous_ts = None
    for call in data["calls"]:
        timestamp = call.get("timestamp")
        delta = round(timestamp - previous_ts, 1) if timestamp and previous_ts else None
        previous_ts = timestamp or previous_ts
        tools = sorted({
            item["tool_name"] for item in call["items"]
            if item["kind"] == "tool_result" and item.get("tool_name")
        })
        rows.append({
            "turn": call["turn"],
            "time": _hhmmss(timestamp),
            "delta_s": delta,
            "input_tokens": call["api_input_tokens"],
            "output_tokens": call["api_output_tokens"],
            "cache_read": call["api_cache_read"],
            "cache_create": call["api_cache_create"],
            "cache_hit_pct": _cache_hit_pct(call),
            "tools": tools,
            "cost": round(calc_cost(
                data["model"], call["api_input_tokens"], call["api_output_tokens"],
                call["api_cache_read"], call["api_cache_create"]), 4),
        })
    return {
        "model": data["model"],
        "system_prompt_tokens": data["system_prompt_tokens"],
        "missing_dumps": bool(data.get("missing_dumps")),
        "calls": rows,
        "total_cost": round(sum(row["cost"] for row in rows), 3),
    }


def _readable_item(item: dict) -> dict:
    return {
        "kind": item["kind"],
        "label": item["label"],
        "est_tokens": item["est_tokens"],
        "cache_status": item["cache_status"],
        "cache_label": CACHE_STATUS_LABELS.get(item["cache_status"], item["cache_status"]),
        "preview": item.get("preview", ""),
        "content": item.get("text", item.get("preview", "")),
    }


def _response_html(session_path: str, turn_index: int) -> str:
    """La réponse du n-ième appel LLM = le n-ième message assistant de la session."""
    data = store.load_session_json(Path(session_path)) or {}
    assistant_messages = [m for m in data.get("messages", []) if m.get("role") == "assistant"]
    if 0 <= turn_index < len(assistant_messages):
        return message_view.render_message(assistant_messages[turn_index])
    return "<p class='muted'>réponse introuvable dans la session</p>"


def turn_detail(session_path: str, turn: int) -> dict | None:
    """Payload exact d'un appel, item par item, annoté cached / new-cache / fresh."""
    data = extract_per_call_data(session_path)
    if data is None:
        return None
    call_index = next(
        (i for i, c in enumerate(data["calls"]) if c["turn"] == turn), None)
    if call_index is None:
        return None
    call = data["calls"][call_index]
    return {
        "turn": turn,
        "items": [_readable_item(item) for item in call["items"]],
        "tokens_by_status": call["tokens_by_status"],
        "wire_message_count": call["wire_message_count"],
        "input_tokens": call["api_input_tokens"],
        "output_tokens": call["api_output_tokens"],
        "cache_read": call["api_cache_read"],
        "cache_create": call["api_cache_create"],
        "response_html": _response_html(session_path, call_index),
    }
