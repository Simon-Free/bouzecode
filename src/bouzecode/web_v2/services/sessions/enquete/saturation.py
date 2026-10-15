# [desc] Ce qui remplit le contexte : composition par catégorie au fil des tours et plus gros morceaux d'un tour (sections de la note comprises). [/desc]
"""Répondre à « qu'est-ce qui sature le contexte ? ».

Catégories : prompt système, note de travail découpée en prose / extraits de code (sections
« ## snippet: »), résultats d'outils, messages. La note est un seul élément du payload mais
porte des centaines de sections : le classement des plus gros morceaux la découpe par section
pour montrer lesquelles pèsent.
"""
from __future__ import annotations

import re

from ....runtime.context_viewer.items import estimate_tokens
from .source import Enquete
from .tour import elements

CATEGORIES = ("systeme", "note_prose", "note_extraits", "resultats_outils", "messages")
LIBELLES = {"systeme": "Prompt système", "note_prose": "Note — prose",
            "note_extraits": "Note — extraits de code", "resultats_outils": "Résultats d'outils",
            "messages": "Messages"}
_SECTION = re.compile(r"^## ", re.MULTILINE)


def _est_note(e: dict) -> bool:
    return e["genre"] == "notes_block" or e["texte"].lstrip().startswith("[METHODOLOGY")


def sections(texte: str) -> list[tuple[str, str]]:
    """Découpe une note en sections (titre, texte) sur les lignes « ## »."""
    debuts = [m.start() for m in _SECTION.finditer(texte)]
    bornes = zip(debuts, debuts[1:] + [len(texte)])
    # Titre = première ligne de la section, prise sans découper toute la section (une note
    # porte des centaines de sections, et la vue la redécoupe pour chaque tour).
    return [(texte[a:b].partition("\n")[0].splitlines()[0][3:].strip(), texte[a:b])
            for a, b in bornes]


def _repartir_note(texte: str) -> dict[str, int]:
    extraits = sum(estimate_tokens(corps) for titre, corps in sections(texte)
                   if titre.lower().startswith("snippet"))
    return {"note_extraits": extraits, "note_prose": max(estimate_tokens(texte) - extraits, 0)}


def _categorie(e: dict) -> str:
    if e["genre"] == "tool_result":
        return "resultats_outils"
    if e["genre"] in ("user", "assistant"):
        return "messages"
    return "systeme"


def composition(appel: dict) -> dict[str, int]:
    parts = dict.fromkeys(CATEGORIES, 0)
    for e in elements(appel):
        if _est_note(e):
            for k, v in _repartir_note(e["texte"]).items():
                parts[k] += v
        else:
            parts[_categorie(e)] += e["tokens"]
    return parts


def _morceaux(appel: dict) -> list[dict]:
    morceaux = []
    for e in elements(appel):
        if _est_note(e):
            morceaux += [{"indice": e["indice"], "libelle": f"Note › {titre[:90]}",
                          "tokens": estimate_tokens(corps), "section": titre}
                         for titre, corps in sections(e["texte"])]
        else:
            morceaux.append({"indice": e["indice"], "libelle": e["libelle"][:100],
                             "tokens": e["tokens"], "section": ""})
    return morceaux


def saturation(enquete: Enquete, tour: int | None = None) -> dict:
    # La composition au fil des tours ne dépend pas du tour ciblé : calculée une fois.
    series = enquete.memoise("saturation_series", lambda: [
        {"tour": c.get("turn"), **composition(c)} for c in enquete.calls])
    cible = enquete.appel(tour) if tour is not None else (enquete.calls[-1] if enquete.calls else None)
    top = sorted(_morceaux(cible), key=lambda m: -m["tokens"])[:20] if cible else []
    return {"categories": list(CATEGORIES), "libelles": LIBELLES, "series": series,
            "tour": cible.get("turn") if cible else None, "plus_gros": top}
