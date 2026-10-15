# [desc] Blueprint Flask : GET /api/env-sanity (verdict env API) et POST /api/env-sanity/recheck (re-sonde à chaud). [/desc]
from flask import Blueprint, jsonify

from .. import api_sanity as _api_sanity

env_sanity_bp = Blueprint("env_sanity", __name__)


@env_sanity_bp.get("/api/env-sanity")
def api_env_sanity():
    """verdict du sanity-check de l'env API fait au boot → {ok, detail, base_url_present,
    key_present} (ANTHROPIC_BASE_URL/clé présentes et base_url joignable) — alimente le bandeau
    rouge et les gardes 503 des endpoints de spawn"""
    return jsonify(_api_sanity.api_sanity_state())


@env_sanity_bp.post("/api/env-sanity/recheck")
def api_env_sanity_recheck():
    """re-sonde l'API MAINTENANT et renvoie le verdict à jour — répare un KO
    transitoire (réseau/proxy) sans redémarrer le serveur"""
    return jsonify(_api_sanity.recheck_api_sanity())
