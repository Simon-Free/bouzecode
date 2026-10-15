# [desc] Signalements non bloquants des agents (outil Signaler) : liste des ouverts et acquittement par l'humain. [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...services.work import signalements
from .._body import json_body
from .._errors import erreur

signalements_bp = Blueprint("signalements_api", __name__)


@signalements_bp.get("/api/signalements")
def api_signalements():
    """signalements ouverts (outil Signaler) → {items:[{id, created_at, gravite, titre, detail,
    action_attendue, agent_id, ticket_slug, ticket_id, parents[], profondeur, acquitte_at}],
    compte}"""
    ouverts = signalements.ouverts()
    return jsonify({"items": ouverts, "compte": len(ouverts)})


@signalements_bp.post("/api/signalements")
def api_signalement_creer():
    """l'humain émet un signalement (même geste que l'outil Signaler d'un agent) {gravite: info |
    alerte | bloquant, titre, detail?, action_attendue?, ticket_slug?, ticket_id?} → 201 {ok,
    signalement} ; 400 `signalement_invalide` (gravité inconnue, titre vide)"""
    body = json_body(request)
    try:
        signalement = signalements.creer(
            body.get("gravite") or "", body.get("titre") or "", detail=body.get("detail") or "",
            action_attendue=body.get("action_attendue") or "", agent_id="humain",
            ticket_slug=body.get("ticket_slug") or "", ticket_id=body.get("ticket_id") or "")
    except ValueError as exc:
        return erreur("signalement_invalide", str(exc), 400)
    return jsonify({"ok": True, "signalement": signalement}), 201


@signalements_bp.post("/api/signalements/<signalement_id>/acquitter")
def api_signalement_acquitter(signalement_id: str):
    """l'humain a pris connaissance : le signalement quitte « À traiter » → {ok, signalement} ; 404
    `signalement_inconnu`"""
    signalement = signalements.acquitter(signalement_id)
    if signalement is None:
        return erreur("signalement_inconnu", f"signalement {signalement_id} inconnu", 404)
    return jsonify({"ok": True, "signalement": signalement})
