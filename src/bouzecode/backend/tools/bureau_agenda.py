# [desc] Outil `Agenda` de l'assistant du Bureau : lit l'agenda Outlook (Graph Calendars.Read), fenetre bornee, lecture seule. [/desc]
"""Outil `Agenda` : l'agenda de l'humain, en lecture seule.

Meme contrat que `Mails` (bureau_tools) : jamais d'exception nue, un refus de
consentement (`Calendars.Read`) est une REPONSE nommee, et `transport` n'est pas expose au
modele (point d'injection des tests). Import paresseux du service : `backend/tools` ne
depend pas de `web_v2` au chargement.
"""
from __future__ import annotations

from typing import Any

from ..core.tool_registry import ToolDef, register_tool


def agenda(fenetre: str = "7j", sens: str = "a_venir", top: int = 0,
           transport: Any = None, maintenant: Any = None) -> dict:
    """Les rendez-vous de l'humain sur la fenetre (`a_venir` ou `passe`)."""
    from bouzecode.web_v2.services.work import ms_activite, ms_agenda

    try:
        return ms_agenda.rapport_agenda(
            str(fenetre or "7j"), str(sens or "a_venir"),
            top=int(top) if top else ms_agenda.TOP_EVENEMENTS,
            transport=transport, maintenant=maintenant)
    except ms_activite.TeamsAuthError as souci:
        return {"ok": False, "erreur": "authentification", "message": str(souci),
                "consigne": "Dis a l'humain que la lecture de son agenda n'est pas autorisee "
                            "(consentement Calendars.Read a accorder). N'invente aucun "
                            "rendez-vous et ne dis pas qu'un creneau est libre."}
    except ms_activite.TeamsTransportError as souci:
        return {"ok": False, "erreur": "transport", "message": str(souci),
                "consigne": "L'agenda n'a PAS ete lu : dis-le, ne conclus rien sur les creneaux."}
    except ValueError as souci:
        return {"ok": False, "erreur": "fenetre_invalide", "message": str(souci)}


AGENDA_SCHEMA = {
    "name": "Agenda",
    "description": (
        "L'agenda Outlook de l'humain (lecture seule, Microsoft Graph Calendars.Read). "
        "sens='a_venir' (defaut) : de ce matin a maintenant + fenetre — ses rendez-vous, "
        "ses creneaux pris AVANT de proposer `Creneau` ou `Reunion`. sens='passe' : les "
        "reunions tenues sur la fenetre, a croiser avec la TODO (une reunion laisse souvent "
        "des actions). Fenetre STRICTE '2j', '7j' ou '30j'. `tronque: true` = le plafond "
        "`top` a coupe : rappelle avec un `top` plus grand avant d'affirmer qu'un creneau "
        "est libre. Refus d'acces = l'outil te le DIT : repete-le, n'invente rien."),
    "input_schema": {"type": "object", "properties": {
        "fenetre": {"type": "string", "enum": ["2j", "7j", "30j"],
                    "description": "Duree couverte. Defaut '7j'."},
        "sens": {"type": "string", "enum": ["a_venir", "passe"],
                 "description": "Vers l'avant (defaut) ou vers l'arriere."},
        "top": {"type": "integer",
                "description": "Nombre MAXIMUM d'evenements (defaut 100)."},
    }, "required": []},
}


def register() -> None:
    """Enregistre `Agenda` (desactive par defaut : seul un profil qui le declare l'allume)."""
    register_tool(ToolDef(
        name="Agenda", schema=AGENDA_SCHEMA,
        func=lambda p, c: agenda(p.get("fenetre") or "7j", p.get("sens") or "a_venir",
                                 top=int(p.get("top") or 0)),
        read_only=True, concurrent_safe=True))
