# [desc] Analyse par appel LLM: durées, tokens, cache hit, coût + drill-down payload annoté. [/desc]
"""Réutilise web.context_viewer (v1) : dumps exacts de payload + annotation cache.

`turn_table` répond à « où l'agent a perdu du temps » ; `turn_detail` répond à
« que contenait exactement ce tour, qu'est-ce qui était caché ou non ».
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ....backend.agent.providers.registry import calc_cost
from ...runtime.context_viewer.builder import extract_per_call_data, memoriser
from .. import message_view
from . import store

CACHE_STATUS_LABELS = {"cached": "caché", "new-cache": "écrit au cache", "fresh": "plein tarif"}


def _hhmmss(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _cache_hit_pct(call: dict) -> int:
    """Part du prompt servie par le cache, en %. TOUJOURS entre 0 et 100.

    `api_input_tokens` est le prompt NON lu en cache (frais + écriture de cache) : il
    n'inclut PAS `api_cache_read`. Le prompt total est donc la somme des deux — diviser
    par le seul `api_input_tokens` rendait des taux impossibles (322 %, 698 %, 1599 %
    observés en production) et faisait mentir toutes les vues qui l'affichent.
    """
    denominator = call["api_input_tokens"] + call["api_cache_read"]
    return round(100 * call["api_cache_read"] / denominator) if denominator else 0


def turn_table(session_path: str) -> dict | None:
    """Tableau des appels LLM. Δ = temps depuis l'appel précédent (LLM + outils).

    Mémorisé par version de la session et du journal (`builder.memoriser`) : ne pas modifier
    le résultat."""
    return memoriser("turn_table", session_path, lambda: _turn_table(session_path),
                     depuis_extrait=True)


def _turn_table(session_path: str) -> dict | None:
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
            "output_estimated": bool(call.get("api_output_estimated")),
            "input_estimated": bool(call.get("api_input_estimated")),
            "tools": tools,
            "cost": round(calc_cost(
                data["model"], call["api_input_tokens"], call["api_output_tokens"],
                call["api_cache_read"], call["api_cache_create"]), 4),
        })
    # Les appels annexes (résumé de réflexion, classifieur, rattrapage, compaction) ne sont
    # pas des tours : ils n'ont pas de ligne, mais leur coût entre dans le total pour que
    # /turns et /costs annoncent LE MÊME coût de session.
    from .costs import _side_calls
    side = _side_calls(session_path)
    side_cost = sum(calc_cost(e.get("model") or data["model"], e["api_input_tokens"],
                              e["api_output_tokens"], e["api_cache_read"],
                              e["api_cache_create"]) for e in side)
    return {
        "model": data["model"],
        "system_prompt_tokens": data["system_prompt_tokens"],
        "missing_dumps": bool(data.get("missing_dumps")),
        "calls": rows,
        "side_calls": {"count": len(side), "cost": round(side_cost, 4)},
        "total_cost": round(sum(row["cost"] for row in rows) + side_cost, 3),
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
    """La réponse du n-ième appel LLM = le n-ième message assistant de la session (rendu
    mémorisé par version de la session : relire 100 Mo pour un message coûtait 0,5 s)."""
    return memoriser(f"reponse_html:{turn_index}", session_path,
                     lambda: _response_html_lu(session_path, turn_index))


def _response_html_lu(session_path: str, turn_index: int) -> str:
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
