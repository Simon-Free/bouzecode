# [desc] Recherche plein texte dans toute une session : payloads, ajouts à la note, réponses et résultats d'outils, sans doublons tour après tour. [/desc]
"""Trouver le tour où un mot, un chemin ou une erreur apparaît.

Pour ne pas renvoyer 100 fois la même ligne d'un préfixe répété à chaque tour, chaque texte
n'est cherché que la première fois qu'il apparaît (bloc système, message), et la note par
ses AJOUTS tour par tour.
"""
from __future__ import annotations

import json

from . import marqueurs as mq
from .methodologie import historique
from .source import Enquete
from .tour import elements

LIMITE = 200
CONTEXTE = 90


def _extrait(texte: str, pos: int, longueur: int) -> str:
    debut = max(pos - CONTEXTE, 0)
    fin = min(pos + longueur + CONTEXTE, len(texte))
    return ("…" if debut else "") + texte[debut:fin].replace("\n", " ") + ("…" if fin < len(texte) else "")


def _occurrences(texte: str, q: str):
    bas = texte.lower()
    pos = bas.find(q)
    while pos != -1:
        yield pos
        pos = bas.find(q, pos + len(q))


def _chercher(textes, q: str, resultats: list[dict]) -> None:
    for tour, ou, indice, texte in textes:
        for pos in _occurrences(texte, q):
            resultats.append({"tour": tour, "ou": ou, "indice": indice,
                              "extrait": _extrait(texte, pos, len(q))})
            if len(resultats) >= LIMITE:
                return


def _payloads(enquete: Enquete):
    vus = set()
    for appel in enquete.calls:
        for e in elements(appel):
            if e["texte"].lstrip().startswith("[METHODOLOGY") or e["texte"] in vus:
                continue
            vus.add(e["texte"])
            yield appel.get("turn"), "payload", e["indice"], e["texte"]


def _reponses(enquete: Enquete):
    for appel, r in zip(enquete.calls, enquete.reponses):
        a = r["assistant"]
        corps = mq.texte(a.get("content")) + "\n" + json.dumps(
            [tc.get("input") for tc in a.get("tool_calls") or []], ensure_ascii=False)
        yield appel.get("turn"), "reponse", None, corps
        for m in r["resultats"]:
            yield appel.get("turn"), f"resultat:{m.get('name', '?')}", None, mq.texte(m.get("content"))


def _note(enquete: Enquete):
    for e in historique(enquete)["entrees"]:
        yield e["tour"], "note", None, e["ajoute"]


def rechercher(enquete: Enquete, q: str) -> dict:
    q = (q or "").strip().lower()
    if len(q) < 2:
        return {"q": q, "resultats": [], "limite_atteinte": False}
    resultats: list[dict] = []
    for source in (_note(enquete), _payloads(enquete), _reponses(enquete)):
        _chercher(source, q, resultats)
        if len(resultats) >= LIMITE:
            break
    resultats.sort(key=lambda r: (r["tour"] or 0))
    return {"q": q, "resultats": resultats, "limite_atteinte": len(resultats) >= LIMITE}
