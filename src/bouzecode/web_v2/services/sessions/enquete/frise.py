# [desc] La frise d'une session : une ligne par tour (tokens par statut de cache, sortie, coût, durée, outils, marqueurs). [/desc]
"""Une ligne par appel LLM, de quoi repérer d'un coup d'œil le tour qui déraille."""
from __future__ import annotations

from .....backend.agent.providers.registry import calc_cost
from . import marqueurs as mq
from .source import Enquete


def _outils(reponse: dict | None) -> list[str]:
    if not reponse:
        return []
    return [tc.get("name", "?") for tc in reponse["assistant"].get("tool_calls") or []]


def _annexes_par_tour(enquete: Enquete) -> dict[int, list[dict]]:
    par_tour: dict[int, list[dict]] = {}
    for entree in enquete.data.get("compaction_log") or []:
        if entree.get("event") == "side_call":
            par_tour.setdefault(int(entree.get("turn") or 0), []).append(entree)
    return par_tour


def _cout(modele: str, appel: dict) -> float:
    return calc_cost(modele, appel.get("api_input_tokens", 0), appel.get("api_output_tokens", 0),
                     appel.get("api_cache_read", 0), appel.get("api_cache_create", 0))


def _ligne(enquete: Enquete, i: int, annexes: dict[int, list[dict]]) -> dict:
    appel = enquete.calls[i]
    precedent = enquete.calls[i - 1] if i else None
    tour = appel.get("turn")
    reponse = enquete.reponses[i] if i < len(enquete.reponses) else None
    duree = None
    if precedent and appel.get("timestamp") and precedent.get("timestamp"):
        duree = round(appel["timestamp"] - precedent["timestamp"], 1)
    marques = mq.marqueurs(appel, precedent, enquete.dumps.get(tour),
                           enquete.dumps.get(precedent.get("turn")) if precedent else None,
                           reponse)
    return {
        "tour": tour, "horodatage": appel.get("timestamp"), "duree_s": duree,
        "plein_tarif": appel.get("api_input_tokens", 0), "cache_lu": appel.get("api_cache_read", 0),
        "cache_ecrit": appel.get("api_cache_create", 0), "sortie": appel.get("api_output_tokens", 0),
        "sortie_estimee": bool(appel.get("api_output_estimated")),
        "cout": round(_cout(enquete.data.get("model") or "", appel), 5),
        "outils": _outils(reponse), "marqueurs": marques,
        "anormal": any(m in mq.ANORMAUX for m in marques),
        "annexes": len(annexes.get(tour, [])),
        "fournisseur": appel.get("provider", ""),
        "cause_cache": mq.cause_du_rate(appel, precedent),
    }


def frise(enquete: Enquete) -> dict:
    annexes = _annexes_par_tour(enquete)
    lignes = [_ligne(enquete, i, annexes) for i in range(len(enquete.calls))]
    return {
        "agent_id": enquete.agent_id, "modele": enquete.data.get("model") or "",
        "tours": lignes, "libelles_marqueurs": mq.LIBELLES,
        "total_cout": round(sum(ligne["cout"] for ligne in lignes), 4),
        "nb_anormaux": sum(1 for ligne in lignes if ligne["anormal"]),
    }
