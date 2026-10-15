# [desc] Analyse d'une session par appel LLM : table des tours, coûts (avec sous-agents), payload exact d'un tour, zoom lisible, tool_call intégral, diagnostic du contexte injecté. LECTURE PURE. [/desc]
from __future__ import annotations

from flask import jsonify, make_response, request

from ...services.erreurs import Refus
from ...services.sessions import analysis, costs
from . import sessions_bp
from ._commun import donnees_ou_404, json_ou_texte, session_ou_404

_SANS_JOURNAL = "session sans compaction_log (trop ancienne ou vide)"


@sessions_bp.get("/api/sessions/<path:key>/turns")
def api_session_turns(key: str):
    """par appel LLM: heure, delta_s, tokens in/out, cache lu/écrit, %hit, outils, coût"""
    table = analysis.turn_table(str(session_ou_404(key).path))
    if table is None:
        return jsonify({"calls": [], "missing_dumps": True, "note": _SANS_JOURNAL})
    return jsonify(table)


@sessions_bp.get("/api/sessions/<path:key>/costs")
def api_session_costs(key: str):
    """agrégats coûts session: par modèle + total (tokens in/out, cache lu/écrit, %hit, coût en
    unités du tarif) ; ?avec_sous_agents=1 ajoute `sous_agents` [{agent_id, parent, titre, cost,
    calls, unpriced}] et `total_avec_sous_agents`"""
    ref = session_ou_404(key)
    result = costs.session_costs(str(ref.path))
    if result is None:
        result = {"models": {}, "total": None, "note": _SANS_JOURNAL}
    if request.args.get("avec_sous_agents") and ref.agent is not None:
        propre = float((result.get("total") or {}).get("cost") or 0)
        result.update(costs.couts_avec_sous_agents(ref.agent.agent_id, propre))
    return jsonify(result)


@sessions_bp.get("/api/sessions/<path:key>/turns/<int:turn>")
def api_session_turn_detail(key: str, turn: int):
    """payload exact du tour, items annotés cached/new-cache/fresh + réponse ; 404
    `tour_introuvable` (dumps absents ?)"""
    detail = analysis.turn_detail(str(session_ou_404(key).path), turn)
    if detail is None:
        raise Refus("tour_introuvable", f"tour {turn} introuvable (dumps absents ?)", 404)
    return jsonify(detail)


@sessions_bp.get("/api/sessions/<path:key>/turns/<int:n>/view")
def api_session_turn_view(key: str, n: int):
    """zoom lisible sur un tour suspect: messages user/assistant, tool_calls avec résumé résultats.
    ?thinking=1 inclut les blocs thinking. Plain text par défaut, ?json=1 en JSON. 404
    `session_inconnue` / `tour_introuvable`."""
    from ...services.sessions.turn_view import format_turn_plain, format_turn_view
    data = donnees_ou_404(session_ou_404(key))
    result = format_turn_view(data.get("messages") or [], key, n,
                              thinking=request.args.get("thinking", "0") == "1")
    if result is None:
        raise Refus("tour_introuvable", f"tour {n} introuvable", 404)
    return json_ou_texte(result, format_turn_plain)


@sessions_bp.get("/api/sessions/<path:key>/calls/<call_id>")
def api_session_call_zoom(key: str, call_id: str):
    """contenu intégral d'un tool_call (arguments + output complet). Pour inspecter un dump
    volumineux sans polluer la vue d'ensemble. 404 `appel_introuvable`."""
    from ...services.sessions.call_zoom import format_call_plain, get_call_detail
    data = donnees_ou_404(session_ou_404(key))
    result = get_call_detail(data.get("messages") or [], call_id)
    if result is None:
        raise Refus("appel_introuvable", f"call_id '{call_id}' introuvable", 404)
    return json_ou_texte(result, format_call_plain)


@sessions_bp.get("/api/sessions/<path:key>/turns/<int:n>/context")
def api_session_turn_context(key: str, n: int):
    """diagnostic du contexte injecté au modèle pour le tour n. HTML riche par défaut, ?json=1 →
    payload brut. 404 `diagnostic_introuvable` si aucun diagnostic pour ce tour."""
    from ...services.sessions.context_diag import build_turn_context_diag
    from ...services.sessions.context_diag_render import render_context_diag_html
    from ...services.sessions.formatter import pretty_json
    diag = build_turn_context_diag(str(session_ou_404(key).path), n)
    if diag is None:
        raise Refus("diagnostic_introuvable", f"aucun diagnostic pour le tour {n}", 404)
    if request.args.get("json"):
        resp = make_response(pretty_json(diag))
        resp.headers["Content-Type"] = "application/json"
        return resp
    resp = make_response(render_context_diag_html(diag))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp
