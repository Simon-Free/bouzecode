# [desc] Outil always-on `Signaler` : un agent fait remonter un probleme a l'humain SANS s'arreter (AskUserQuestion reste l'outil du blocage). [/desc]
"""`Signaler(gravite, titre, detail, action_attendue?)` — non bloquant.

Identite de l'appelant : l'agent web (nom du dossier IPC, ticket du runner), sinon l'identite
de l'assistant du terminal (`BOUZECODE_TUI_PARENT`), sinon `process:<pid>`. Le signalement
est ecrit dans le store du Bureau (`web_v2.services.work.signalements`) dans tous les cas :
la base est un fichier, un TUI y ecrit sans serveur, et l'humain le voit au prochain
affichage du Bureau.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..core.tool_registry import ToolDef, register_tool

ENV_TUI = "BOUZECODE_TUI_PARENT"


def identite_appelant() -> str:
    ipc = os.environ.get("BOUZECODE_WEB_IPC_DIR") or ""
    if ipc:
        return Path(ipc).stem
    return os.environ.get(ENV_TUI) or f"process:{os.getpid()}"


def signaler(params: dict, config: dict) -> str:
    from bouzecode.web_v2.services.work import profondeur, signalements

    agent_id = identite_appelant()
    parent = os.environ.get("BOUZECODE_PARENT") or ""
    try:
        signalement = signalements.creer(
            params.get("gravite") or "", params.get("titre") or "",
            detail=params.get("detail") or "", action_attendue=params.get("action_attendue") or "",
            agent_id=agent_id, parents=profondeur.chaine_depuis(parent),
            ticket_slug=os.environ.get("BOUZECODE_TICKET_SLUG") or "",
            ticket_id=os.environ.get("BOUZECODE_TICKET_ID") or "")
    except ValueError as souci:
        return f"Error: signalement refuse — {souci}."
    return (f"Signalement {signalement['id']} enregistre ({signalement['gravite']}) : l'humain le "
            "voit dans « A traiter », tes ancetres le recevront a leur prochain reveil. "
            "CONTINUE ton travail ; si tu ne peux vraiment pas avancer, c'est AskUserQuestion.")


SIGNALER_SCHEMA = {
    "name": "Signaler",
    "description": (
        "Fait remonter un probleme a l'humain SANS t'arreter : il apparait dans « A traiter » "
        "et chez tes agents parents, tu continues ton travail. Bloque sans pouvoir avancer -> "
        "AskUserQuestion ; probleme a connaitre mais tu peux continuer -> Signaler. "
        "gravite : 'info' (a savoir), 'alerte' (risque, resultat degrade, contournement "
        "pris), 'bloquant' (une partie ne pourra pas etre faite sans l'humain, tu avances sur "
        "le reste). Un signalement par probleme, pas de doublon."),
    "input_schema": {"type": "object", "properties": {
        "gravite": {"type": "string", "enum": ["info", "alerte", "bloquant"]},
        "titre": {"type": "string", "description": "Une ligne : ce que l'humain doit savoir."},
        "detail": {"type": "string", "description": "Faits mesures, fichiers, erreurs exactes."},
        "action_attendue": {"type": "string",
                            "description": "Optionnel : ce que l'humain devrait faire."},
    }, "required": ["gravite", "titre", "detail"]},
}


def register() -> None:
    register_tool(ToolDef(name="Signaler", schema=SIGNALER_SCHEMA, func=signaler,
                          read_only=False, concurrent_safe=True))
