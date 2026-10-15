# [desc] Un tour à la loupe : payload élément par élément (tokens, cache), diff avec le tour précédent, premier élément qui casse le préfixe, réponse du modèle. [/desc]
"""Répondre à « que contenait exactement ce tour, qu'est-ce qui a changé, pourquoi le cache a
raté, et qu'a répondu le modèle ».

Identité d'un élément d'un tour à l'autre : le N-ième bloc système, la note par son nom, un
message par sa position et son rôle. Le PREMIER élément (dans l'ordre d'envoi) dont le texte
diffère du tour précédent casse le préfixe mis en cache : tout ce qui le suit est relu au
plein tarif ou réécrit dans le cache.
"""
from __future__ import annotations

import re

from . import marqueurs as mq
from .source import Enquete

APERCU = 4000
_REFLEXION = re.compile(r"<thinking>(.*?)(?:</thinking>|$)", re.DOTALL)


def cle(item: dict, rang_systeme: int) -> str:
    kind = item.get("kind", "")
    if kind in ("system_block", "system"):
        return f"systeme:{rang_systeme}"
    if kind == "notes_block":
        return "note"
    return f"message:{item.get('payload_idx')}:{kind}:{item.get('tool_call_id', '')}"


def elements(appel: dict) -> list[dict]:
    """Les éléments d'un appel, chacun avec sa clé stable et son texte intégral."""
    sortie, rang = [], 0
    for i, item in enumerate(appel.get("items") or []):
        sortie.append({"indice": i, "cle": cle(item, rang), "genre": item.get("kind", ""),
                       "libelle": item.get("label", ""), "tokens": item.get("est_tokens", 0),
                       "cache": item.get("cache_status", "fresh"), "texte": item.get("text") or ""})
        if item.get("kind") in ("system_block", "system"):
            rang += 1
    return sortie


def _changement(avant: str, apres: str) -> dict:
    commun = 0
    borne = min(len(avant), len(apres))
    while commun < borne and avant[commun] == apres[commun]:
        commun += 1
    if commun == len(avant):
        return {"nature": "ajout_en_fin", "ajoutes": len(apres) - len(avant), "position": commun}
    return {"nature": "modifie", "position": commun, "avant": avant[commun:commun + 300],
            "apres": apres[commun:commun + 300], "ecart_taille": len(apres) - len(avant)}


def diff(courants: list[dict], precedents: list[dict] | None) -> dict:
    if precedents is None:
        return {"premier_tour": True, "rupture": None, "ajoutes": [], "modifies": [], "retires": []}
    avant = {e["cle"]: e for e in precedents}
    ajoutes = [e["indice"] for e in courants if e["cle"] not in avant]
    modifies = _modifies(courants, avant)
    changes = set(ajoutes) | {m["indice"] for m in modifies}
    rupture = next((e["indice"] for e in courants if e["indice"] in changes), None)
    return {"premier_tour": False, "rupture": rupture, "ajoutes": ajoutes,
            "modifies": modifies, "retires": _retires(courants, precedents)}


def _modifies(courants: list[dict], avant: dict) -> list[dict]:
    return [{"indice": e["indice"], **_changement(avant[e["cle"]]["texte"], e["texte"])}
            for e in courants if e["cle"] in avant and avant[e["cle"]]["texte"] != e["texte"]]


def _retires(courants: list[dict], precedents: list[dict]) -> list[dict]:
    presents = {e["cle"] for e in courants}
    return [{"cle": p["cle"], "libelle": p["libelle"], "tokens": p["tokens"]}
            for p in precedents if p["cle"] not in presents]


def _appel_outil(tc: dict) -> dict:
    return {"nom": tc.get("name", "?"), "id": tc.get("id", ""), "entree": tc.get("input") or {}}


def _resultat(msg: dict) -> dict:
    corps = mq.texte(msg.get("content"))
    return {"nom": msg.get("name", "?"), "id": msg.get("tool_call_id", ""),
            "texte": corps[:APERCU], "tronque": len(corps) > APERCU, "taille": len(corps)}


def reponse(enquete: Enquete, i: int) -> dict | None:
    if i >= len(enquete.reponses):
        return None
    r = enquete.reponses[i]
    assistant = r["assistant"]
    brut = mq.texte(assistant.get("content"))
    reflexion = "\n\n".join(m.strip() for m in _REFLEXION.findall(brut))
    reflexion = reflexion or mq.texte(assistant.get("thinking") or assistant.get("reasoning") or "")
    return {"texte": _REFLEXION.sub("", brut).strip(), "reflexion": reflexion,
            "appels": [_appel_outil(tc) for tc in assistant.get("tool_calls") or []],
            "resultats": [_resultat(m) for m in r["resultats"]]}


def _annexes(enquete: Enquete, tour: int) -> list[dict]:
    return [{k: e.get(k) for k in ("model", "label", "api_input_tokens", "api_output_tokens",
                                   "api_cache_read")}
            for e in enquete.data.get("compaction_log") or []
            if e.get("event") == "side_call" and e.get("turn") == tour]


def _public(e: dict) -> dict:
    texte = e["texte"]
    return {**{k: v for k, v in e.items() if k != "texte"},
            "apercu": texte[:APERCU], "tronque": len(texte) > APERCU, "taille": len(texte)}


def detail(enquete: Enquete, tour: int) -> dict | None:
    i = enquete.indice(tour)
    if i is None:
        return None
    appel = enquete.calls[i]
    courants = elements(appel)
    precedents = elements(enquete.calls[i - 1]) if i else None
    return {
        "tour": tour, "precedent": enquete.calls[i - 1]["turn"] if i else None,
        "suivant": enquete.calls[i + 1]["turn"] if i + 1 < len(enquete.calls) else None,
        "api": {k: appel.get(k, 0) for k in ("api_input_tokens", "api_cache_read",
                                             "api_cache_create", "api_output_tokens")},
        "elements": [_public(e) for e in courants], "diff": diff(courants, precedents),
        "reponse": reponse(enquete, i), "annexes": _annexes(enquete, tour),
        "cause_cache": mq.cause_du_rate(appel, enquete.calls[i - 1] if i else None),
    }


def element(enquete: Enquete, tour: int, indice: int) -> dict | None:
    appel = enquete.appel(tour)
    if appel is None:
        return None
    tous = elements(appel)
    return tous[indice] if 0 <= indice < len(tous) else None
