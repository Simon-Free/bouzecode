# [desc] Outil `Projets` de l'assistant : projets enregistres et fichiers non suivis a transmettre a l'agent lance (lecture seule). [/desc]
"""Outil `Projets` : le seul travail « technique » de l'assistant avant de deleguer.

Choisir les projets pertinents, puis la liste des fichiers NON SUIVIS a transmettre a
l'agent (il part de l'etat commite). Lecture seule, import paresseux du service.
"""
from __future__ import annotations

from ..core.tool_registry import ToolDef, register_tool


def projets(action: str = "lister", slug: str = "", indices=None) -> dict:
    from bouzecode.web_v2.services.work import projets_etat

    geste = (action or "lister").strip().lower()
    if geste == "lister":
        return {"ok": True, "projets": projets_etat.lister()}
    if geste == "fichiers":
        if not str(slug or "").strip():
            return {"ok": False, "erreur": "slug_requis",
                    "message": "Quel projet ? Donne `slug` (Projets(action='lister'))."}
        return projets_etat.fichiers(slug, indices)
    return {"ok": False, "erreur": "action_inconnue", "attendu": ["lister", "fichiers"]}


PROJETS_SCHEMA = {
    "name": "Projets",
    "description": (
        "Les projets (depots) enregistres, en lecture seule. action='lister' (defaut) : slug, "
        "chemin, description, branche, dernier commit, .venv present. action='fichiers' "
        "(slug + indices = mots de la tache) : etat git (branche, HEAD, commits non pousses, "
        "modifications non commitees) et fichiers NON SUIVIS avec taille ; `proposes` = ceux "
        "qui semblent utiles a la tache (indices retrouves dans le chemin). Binaires, gros "
        "fichiers et temp_* sont exclus ; les secrets (.env*, cles) sont SIGNALES et ne se "
        "transmettent jamais sans accord explicite de l'humain. Sers-t'en pour remplir "
        "`projets` et `fichiers_non_suivis` de Taches(lancer) / LancerAgent."),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["lister", "fichiers"]},
        "slug": {"type": "string", "description": "Projet vise, pour 'fichiers'."},
        "indices": {"type": "array", "items": {"type": "string"}, "description": (
            "Mots-cles de la tache (noms de modules, de dossiers, de sujets) pour reperer "
            "les fichiers non suivis pertinents. Vide : tout ce qui n'est pas exclu.")},
    }, "required": []},
}


def register() -> None:
    register_tool(ToolDef(name="Projets", schema=PROJETS_SCHEMA,
                          func=lambda p, c: projets(p.get("action") or "lister",
                                                    p.get("slug") or "", p.get("indices")),
                          read_only=True, concurrent_safe=True))
