# [desc] Routes de l'assistant du Bureau : historique de ses conversations et contexte perso. [/desc]
"""L'assistant du Bureau n'a pas de stockage propre : ses conversations SONT des sessions web
de profil `bureau-assistant`, et son contexte perso est un markdown du dossier utilisateur
(`services/work/bureau_contexte.py`) concaténé au prompt de chaque agent de ce profil."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from .._body import json_body
from ...services.sessions import store as sessions_store
from ...services.work import bureau_contexte

assistant_bp = Blueprint("assistant", __name__)

#  C'est le profil qui identifie les conversations de l'assistant : chaque session web porte
#  `typology = agent.profile` (services/sessions/store.py).
TYPOLOGIE_ASSISTANT = "bureau-assistant"


def _fail(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _premier(session: dict, *champs: str) -> str:
    for champ in champs:
        if session.get(champ):
            return session[champ]
    return ""


def _etat(session: dict) -> str:
    """`status` est un dict (store.agent_status) : on sert son `state`, une chaîne."""
    status = session.get("status")
    if isinstance(status, dict):
        return status.get("state", "")
    return session.get("state") or status or ""


def _conversation(session: dict) -> dict | None:
    if _premier(session, "typology", "profile") != TYPOLOGIE_ASSISTANT:
        return None
    key = _premier(session, "key", "id")
    if not key:
        return None
    return {
        "key": key,
        "ticket_id": session.get("ticket_id") or "",
        "title": _premier(session, "title", "subject", "prompt") or key,
        "started_at": _premier(session, "started_at", "created_at", "mtime"),
        "state": _etat(session),
        "need_input": bool(session.get("need_input")),
    }


@assistant_bp.get("/api/bureau/assistant/conversations")
def bureau_assistant_conversations():
    """Les conversations passées avec l'assistant du Bureau, la plus récente d'abord.

    Le front reprend une conversation en repointant son `key` (le fil se recharge par
    /api/sessions/<key>/blocks) et continue d'y écrire grâce à `ticket_id`.
    """
    try:
        sessions = sessions_store.list_agent_sessions(include_tests=False)
    except Exception as erreur:  # pragma: no cover - dépend du disque des sessions
        #  L'historique est un confort : s'il échoue, l'assistant doit rester utilisable.
        return jsonify({"conversations": [], "error": str(erreur)})
    conversations = [c for c in map(_conversation, sessions) if c]
    conversations.sort(key=lambda c: (str(c["started_at"]), str(c["key"])), reverse=True)
    return jsonify({"conversations": conversations})


@assistant_bp.get("/api/bureau/assistant/contexte")
def bureau_assistant_contexte_lire():
    """Le contexte perso que l'utilisateur ajoute au system prompt de son assistant.

    Le texte vit dans un markdown du dossier de configuration de l'utilisateur, que
    `backend/core/profile_extra.py` concatène en dernier au prompt de tout agent de ce profil.
    """
    return jsonify({
        "contenu": bureau_contexte.lire_contexte(),
        "chemin": str(bureau_contexte.chemin_contexte()),
        "profil": bureau_contexte.PROFIL_ASSISTANT,
    })


@assistant_bp.put("/api/bureau/assistant/contexte")
def bureau_assistant_contexte_ecrire():
    """Enregistre le contexte perso (remplacement intégral du fichier).

    Il prend effet au PROCHAIN agent lancé (le prompt est assemblé au démarrage du
    sous-processus), pas dans la conversation en cours.
    """
    corps = json_body(request) or {}
    contenu = corps.get("contenu")
    if contenu is None:
        contenu = corps.get("contenu_md") or ""
    if not isinstance(contenu, str):
        return _fail("bad_contenu", "Le contexte doit être du texte.", 400)
    try:
        chemin = bureau_contexte.ecrire_contexte(contenu)
    except OSError as erreur:
        return _fail("write_failed", f"Impossible d'écrire le contexte : {erreur}", 500)
    return jsonify({"ok": True, "chemin": str(chemin), "contenu": bureau_contexte.lire_contexte()})
