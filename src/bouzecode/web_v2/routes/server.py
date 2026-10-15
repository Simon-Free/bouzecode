# [desc] Redemarrer / arreter le serveur depuis le serveur lui-meme (personne d'autre n'en a le droit).
from flask import Blueprint, jsonify, request

from ..services import server_control

server_bp = Blueprint("server_api", __name__)

PORT_DEFAUT = 5056


def _port_courant() -> int:
    """Le port sur lequel la requete est arrivee : on relance LE MEME serveur."""
    hote = (request.host or "").rsplit(":", 1)
    if len(hote) == 2 and hote[1].isdigit():
        return int(hote[1])
    return PORT_DEFAUT


@server_bp.post("/api/server/restart")
def api_server_restart():
    """Relance le serveur : 202 d'abord (le client doit voir la reponse), mort ensuite."""
    body = request.get_json(silent=True) or {}
    demande = body.get("port")
    port = int(demande) if str(demande or "").isdigit() else _port_courant()
    plan = server_control.plan_restart(port)
    return jsonify({"restarting": True, **plan}), 202


@server_bp.post("/api/server/shutdown")
def api_server_shutdown():
    """Arret sans successeur : c'est l'utilisateur qui relancera (bouzeui.ps1)."""
    plan = server_control.plan_shutdown()
    return jsonify({"stopping": True, **plan}), 202
