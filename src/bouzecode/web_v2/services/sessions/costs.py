# [desc] Session cost aggregation by model with token breakdown, cache hit %, and totals. [/desc]
"""Session cost aggregation: per-model breakdown and session totals.

Reuses the same data pipeline as analysis.turn_table (extract_per_call_data + calc_cost).
"""
from __future__ import annotations

from ....backend.agent.providers.registry import calc_cost
from ....web.context_viewer.builder import extract_per_call_data


def _cache_hit_pct(input_tokens: int, cache_read: int) -> float:
    """Cache hit % = cache_read / (input_tokens + cache_read).

    input_tokens does NOT include cache_read tokens in the API response,
    so total prompt = input_tokens + cache_read.
    """
    total = input_tokens + cache_read
    if not total:
        return 0.0
    return round(cache_read / total * 100, 1)


def session_costs(session_path: str) -> dict | None:
    """Aggregate costs for a session, grouped by model.

    Returns:
        {
            "models": {
                "<model_name>": {
                    "calls": int,
                    "input_tokens": int,
                    "output_tokens": int,
                    "cache_read_tokens": int,
                    "cache_write_tokens": int,
                    "cache_hit_pct": float,
                    "cost": float,
                }
            },
            "total": {
                "calls": int,
                "input_tokens": int,
                "output_tokens": int,
                "cache_read_tokens": int,
                "cache_write_tokens": int,
                "cache_hit_pct": float,
                "cost": float,
            }
        }
    """
    data = extract_per_call_data(session_path)
    if data is None:
        return None

    session_model = data.get("model") or ""
    models: dict[str, dict] = {}

    for call in data["calls"]:
        call_model = call.get("model") or session_model or ""
        bucket = models.setdefault(call_model, {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost": 0.0,
        })
        inp = call["api_input_tokens"]
        out = call["api_output_tokens"]
        cr = call["api_cache_read"]
        cw = call["api_cache_create"]

        bucket["calls"] += 1
        bucket["input_tokens"] += inp
        bucket["output_tokens"] += out
        bucket["cache_read_tokens"] += cr
        bucket["cache_write_tokens"] += cw
        bucket["cost"] += calc_cost(call_model, inp, out, cr, cw) if call_model else 0.0

    # Finalize per-model stats
    unpriced = False
    for model_name, stats in models.items():
        stats["cost"] = round(stats["cost"], 4)
        stats["cache_hit_pct"] = _cache_hit_pct(
            stats["input_tokens"], stats["cache_read_tokens"]
        )
        if not model_name:
            unpriced = True

    # Session total
    total = {
        "calls": sum(m["calls"] for m in models.values()),
        "input_tokens": sum(m["input_tokens"] for m in models.values()),
        "output_tokens": sum(m["output_tokens"] for m in models.values()),
        "cache_read_tokens": sum(m["cache_read_tokens"] for m in models.values()),
        "cache_write_tokens": sum(m["cache_write_tokens"] for m in models.values()),
        "cost": round(sum(m["cost"] for m in models.values()), 4),
    }
    total["cache_hit_pct"] = _cache_hit_pct(
        total["input_tokens"], total["cache_read_tokens"]
    )

    result: dict = {"models": models, "total": total}
    if unpriced:
        result["unpriced"] = True
        result["note"] = "Modèle inconnu pour certains appels — coût affiché = 0 pour ces tours."
    return result
