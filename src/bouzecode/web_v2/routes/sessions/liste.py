# [desc] Lister et chercher les sessions : liste récente, grep regex transversal, téléchargement du JSON brut, file de messages d'un agent. [/desc]
from __future__ import annotations

import re

from flask import jsonify, request, send_file

from ...services.erreurs import Refus
from ...services.sessions import listing_cache, search, store
from ...services.work import file_messages
from . import sessions_bp


@sessions_bp.get("/api/sessions")
def api_sessions_list():
    """agents web + sessions CLI récentes (10 derniers jours). ?include_tests=1 rétablit les
    conversations de test filtrées par défaut."""
    include_tests = request.args.get("include_tests") in ("1", "true", "yes")
    return jsonify(listing_cache.cached_list_sessions(include_tests=include_tests))


@sessions_bp.get("/api/sessions/<path:key>/download")
def api_session_download(key: str):
    """Télécharge le JSON brut de la session (agent/<id> ou daily/<date>/<file>) ; 404
    `session_inconnue`."""
    ref = store.resolve(key)
    if ref is None or not ref.path.is_file():
        raise Refus("session_inconnue", f"session inconnue : {key}", 404, key=key)
    return send_file(ref.path, as_attachment=True, download_name=ref.path.name,
                     mimetype="application/json")


@sessions_bp.get("/api/sessions/grep")
def api_sessions_grep():
    """?q=<regex>&day=&model=&role=&limit=50 — recherche transversale regex dans toutes les
    sessions (messages + tool_calls). 400 `q_requis` / `regex_invalide`."""
    q = request.args.get("q", "").strip()
    if not q:
        raise Refus("q_requis", "paramètre 'q' (regex) obligatoire", 400)
    try:
        re.compile(q)
    except re.error as exc:
        raise Refus("regex_invalide", f"regex invalide : {exc}", 400) from exc
    limit = min(request.args.get("limit", 50, type=int), 200)
    return jsonify(search.grep_sessions(q, day=request.args.get("day"),
                                        model=request.args.get("model"),
                                        role=request.args.get("role"), limit=limit))


@sessions_bp.get("/api/agents/<agent_id>/queue")
def api_agent_queue(agent_id: str):
    """messages en file d'attente pour cet agent (écrits pendant son tour) → {items:[{id, text,
    created_at}]}"""
    return jsonify({"items": file_messages.lister(agent_id)})


@sessions_bp.delete("/api/agents/<agent_id>/queue/<queue_id>")
def api_agent_queue_cancel(agent_id: str, queue_id: str):
    """annule un message en file → {ok} ; 404 `inconnu` s'il est déjà livré"""
    if not file_messages.annuler(agent_id, queue_id):
        raise Refus("inconnu", "message déjà livré ou inconnu", 404, queue_id=queue_id)
    return jsonify({"ok": True})
