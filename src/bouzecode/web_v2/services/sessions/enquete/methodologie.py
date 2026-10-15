# [desc] L'histoire de la note de travail (Methodology) : chaque ajout tour par tour, la taille cumulée, les compactions, la recherche. [/desc]
"""Parcourir tout ce que l'agent a écrit dans sa note, et voir quand elle a été compactée.

Source de vérité : la note RÉELLEMENT envoyée à chaque tour (journal des payloads), comparée
au tour précédent. Un ajout en fin est un « ajout » ; une note plus courte qu'avant est une
« compaction » (on montre ce qui a disparu). On y joint le texte des appels Methodology de la
réponse du tour, c'est-à-dire ce que le modèle a demandé d'écrire.
"""
from __future__ import annotations

import json

from .source import Enquete

APERCU = 3000


def _notes(dump: dict | None) -> str:
    notes = ((dump or {}).get("context_state") or {}).get("notes") or {}
    return "\n\n".join(f"## {nom}\n{contenu}" for nom, contenu in notes.items())


def _variation(avant: str, apres: str) -> dict:
    if apres.startswith(avant):
        return {"ajoute": apres[len(avant):], "retire": 0, "compaction": False}
    commun = 0
    borne = min(len(avant), len(apres))
    while commun < borne and avant[commun] == apres[commun]:
        commun += 1
    return {"ajoute": apres[commun:], "retire": len(avant) - commun,
            "compaction": len(apres) < len(avant), "disparu": avant[commun:commun + APERCU]}


def _appels_methodology(enquete: Enquete, i: int) -> list[str]:
    if i >= len(enquete.reponses):
        return []
    appels = enquete.reponses[i]["assistant"].get("tool_calls") or []
    return [str((tc.get("input") or {}).get("content", "")) for tc in appels
            if tc.get("name") == "Methodology"]


def _entree(enquete: Enquete, i: int, avant: str) -> tuple[dict, str]:
    appel = enquete.calls[i]
    note = _notes(enquete.dumps.get(appel.get("turn")))
    variation = _variation(avant, note)
    ajoute = variation["ajoute"]
    entree = {"tour": appel.get("turn"), "taille": len(note), "retire": variation["retire"],
              "compaction": variation["compaction"], "disparu": variation.get("disparu", ""),
              "ajoute": ajoute[:APERCU], "ajoute_tronque": len(ajoute) > APERCU,
              "taille_ajout": len(ajoute), "appels": _appels_methodology(enquete, i)}
    return entree, note


def _correspond(entree: dict, q: str) -> bool:
    return q in json.dumps(entree, ensure_ascii=False).lower()


def historique(enquete: Enquete, q: str = "") -> dict:
    entrees, avant = [], ""
    for i in range(len(enquete.calls)):
        entree, avant = _entree(enquete, i, avant)
        entrees.append(entree)
    q = q.strip().lower()
    visibles = [e for e in entrees if not q or _correspond(e, q)]
    return {"courbe": [{"tour": e["tour"], "taille": e["taille"]} for e in entrees],
            "compactions": [e["tour"] for e in entrees if e["compaction"]],
            "entrees": visibles, "q": q, "total": len(entrees)}
