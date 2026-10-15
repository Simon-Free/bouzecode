# [desc] Session cost aggregation by model with token breakdown, cache hit %, and totals. [/desc]
"""Session cost aggregation: per-model breakdown and session totals.

Reuses the same data pipeline as analysis.turn_table (extract_per_call_data + calc_cost).
"""
from __future__ import annotations

import json
from pathlib import Path

from ....backend.agent.providers.registry import calc_cost
from ...runtime.context_viewer.builder import extract_per_call_data, memoriser


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
    """Coûts de la session, mémorisés par version de la session et du journal : la vue
    `avec_sous_agents` les demande pour chaque sous-agent, à chaque requête. Copie de premier
    niveau : l'appelant peut y ajouter des clés (la route le fait)."""
    resultat = memoriser("session_costs", session_path, lambda: _session_costs(session_path),
                         depuis_extrait=True)
    return dict(resultat) if resultat is not None else None


def _session_costs(session_path: str) -> dict | None:
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
    # Appels ANNEXES (résumé de réflexion, classifieur, rattrapage, compaction) : facturés
    # comme les autres, journalisés à part par dispatch._record_side_call. Ils entrent dans
    # les totaux et dans un compteur `side_calls` par modèle — sinon le coût affiché de la
    # session ignorait une partie de ce qui a été payé.
    calls = [dict(c, side=False) for c in data["calls"]]
    calls += [dict(c, side=True) for c in _side_calls(session_path)]
    models: dict[str, dict] = {}
    for call in calls:
        call_model = call.get("model") or session_model or ""
        _ajouter_appel(models.setdefault(call_model, _nouveau_compteur()), call, call_model)
    unpriced_models = _finaliser(models)
    result: dict = {"models": models, "total": _total(models)}
    if unpriced_models is not None:
        result["unpriced"] = True
        result["unpriced_models"] = unpriced_models
        detail = f" ({', '.join(unpriced_models)})" if unpriced_models else ""
        result["note"] = ("Modèle sans tarif connu pour certains appels"
                          f"{detail} — coût affiché = 0 pour ces tours.")
    return result


_CHAMPS_TOKENS = (("input_tokens", "api_input_tokens"), ("output_tokens", "api_output_tokens"),
                  ("cache_read_tokens", "api_cache_read"), ("cache_write_tokens", "api_cache_create"))


def _nouveau_compteur() -> dict:
    return {"calls": 0, "side_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0, "cost": 0.0}


def _ajouter_appel(bucket: dict, call: dict, call_model: str) -> None:
    bucket["side_calls" if call["side"] else "calls"] += 1
    bucket["output_estimated_calls"] = (bucket.get("output_estimated_calls", 0)
                                        + int(bool(call.get("api_output_estimated"))))
    bucket["input_estimated_calls"] = (bucket.get("input_estimated_calls", 0)
                                       + int(bool(call.get("api_input_estimated"))))
    for champ, source in _CHAMPS_TOKENS:
        bucket[champ] += call[source]
    if call_model:
        bucket["cost"] += calc_cost(call_model, call["api_input_tokens"], call["api_output_tokens"],
                                    call["api_cache_read"], call["api_cache_create"])


def _finaliser(models: dict) -> list[str] | None:
    """Arrondit, calcule le % de cache, et renvoie les modèles sans tarif (None si aucun).

    Modèle vide OU nommé mais absent de la table de prix : dans les deux cas le coût affiché
    est 0 alors que l'appel a bien été facturé — les deux sont signalés."""
    from bouzecode.backend.agent.providers.registry import is_priced

    unpriced, unpriced_models = False, []
    for model_name, stats in models.items():
        stats["cost"] = round(stats["cost"], 4)
        stats["cache_hit_pct"] = _cache_hit_pct(stats["input_tokens"], stats["cache_read_tokens"])
        if not model_name or not is_priced(model_name):
            unpriced = True
            stats["unpriced"] = True
            if model_name and model_name not in unpriced_models:
                unpriced_models.append(model_name)
    return unpriced_models if unpriced else None


def _total(models: dict) -> dict:
    somme = lambda champ: sum(m.get(champ, 0) for m in models.values())  # noqa: E731
    total = {champ: somme(champ) for champ in
             ("calls", "side_calls", "input_tokens", "output_tokens", "cache_read_tokens",
              "cache_write_tokens")}
    total["cost"] = round(somme("cost"), 4)
    # Appels dont la sortie est ESTIMÉE (le flux n'a jamais livré output_tokens).
    total["output_estimated_calls"] = somme("output_estimated_calls")
    total["cache_hit_pct"] = _cache_hit_pct(total["input_tokens"], total["cache_read_tokens"])
    return total


def _side_calls(session_path: str) -> list[dict]:
    """Entrées `side_call` du compaction_log (même forme api_* que les appels principaux),
    mémorisées par version de la session (liste partagée : ne pas la modifier)."""
    return memoriser("side_calls", session_path, lambda: _side_calls_lus(session_path))


def _side_calls_lus(session_path: str) -> list[dict]:
    try:
        data = json.loads(Path(session_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [e for e in data.get("compaction_log") or [] if e.get("event") == "side_call"]


# ------------------------------------------------------------------ agent + sous-agents


def _descendants(agent_id: str, agents: list) -> list:
    """Tous les sous-agents (récursif) d'un agent, parcours en largeur, sans cycle."""
    enfants_de: dict[str, list] = {}
    for a in agents:
        enfants_de.setdefault(str(a.parent or ""), []).append(a)
    vus, file, sortie = {agent_id}, [agent_id], []
    while file:
        for enfant in enfants_de.get(file.pop(0), []):
            if enfant.agent_id not in vus:
                vus.add(enfant.agent_id)
                sortie.append(enfant)
                file.append(enfant.agent_id)
    return sortie


def _ligne_sous_agent(enfant) -> dict:
    couts = session_costs(str(enfant.session_path)) if enfant.session_path else None
    total = (couts or {}).get("total") or {}
    premiere = (enfant.prompt or "").strip().splitlines()
    return {"agent_id": enfant.agent_id, "parent": enfant.parent,
            "titre": premiere[0][:80] if premiere else "",
            "cost": round(float(total.get("cost") or 0), 4),
            "calls": int(total.get("calls") or 0),
            "unpriced": bool((couts or {}).get("unpriced"))}


def couts_avec_sous_agents(agent_id: str, cout_propre: float) -> dict:
    """Coût de chaque sous-agent (récursif) et total agent + sous-agents — le coût d'une mission
    déléguée n'est pas celui du seul agent principal."""
    from ...runtime.runner import agent_registre
    lignes = [_ligne_sous_agent(e) for e in _descendants(agent_id, agent_registre.list_agents())]
    return {"sous_agents": lignes,
            "total_avec_sous_agents": round(cout_propre + sum(l["cost"] for l in lignes), 4)}
