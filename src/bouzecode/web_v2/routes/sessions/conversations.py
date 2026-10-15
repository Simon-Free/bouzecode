# [desc] Ranger les conversations : candidats de test, purge (corbeille), archivage réversible (une ou plusieurs), orphelines en attente, restauration. [/desc]
from __future__ import annotations

from flask import jsonify, request

from ...services.erreurs import Refus
from ...services.sessions import purge
from .._body import json_body
from . import sessions_bp


def _liste(cle: str) -> list:
    valeurs = json_body(request).get(cle) or []
    if not isinstance(valeurs, list):
        raise Refus("liste_attendue", f"{cle} doit être une liste", 400)
    return valeurs


@sessions_bp.get("/api/conversations/test-candidates")
def api_conversations_test_candidates():
    """Aperçu des conversations de test (heuristique titre/prompt), NON running."""
    return jsonify({"candidates": purge.list_test_candidates()})


@sessions_bp.post("/api/conversations/purge-tests")
def api_conversations_purge_tests():
    """{agent_ids: [...]} — soft-delete (corbeille) des conversations de TEST listées ; double
    filtre heuristique côté service, une vraie conversation n'est jamais touchée. 400
    `liste_attendue` si agent_ids n'est pas une liste."""
    return jsonify(purge.purge_agents(_liste("agent_ids")))


@sessions_bp.post("/api/conversations/<agent_id>/archive")
def api_conversation_archive(agent_id: str):
    """Archive (rangement réversible) une conversation quelconque, y compris une vraie
    conversation user finie. Refuse un agent inconnu.

    N'écrit QUE dans le registre des archivés : rien n'est déplacé sur disque (le
    déplacement a rendu un manager vivant injoignable le 2026-07-28, cf. purge.archive_agents),
    et un agent encore vivant reste visible malgré le drapeau (cf. sessions/visibility.py)."""
    return jsonify(purge.archive_agents([agent_id]))


@sessions_bp.get("/api/conversations/stale-need-input")
def api_conversations_stale_need_input():
    """conversations bloquées en 'need input' avec un process MORT (orphelines) →
    {candidates:[...]}, archivables en masse via /api/conversations/archive."""
    return jsonify({"candidates": purge.stale_need_input_candidates()})


@sessions_bp.post("/api/conversations/archive")
def api_conversations_archive():
    """{keys: ['agent/<id>', ...]} — archive (soft-delete réversible) une ou plusieurs
    conversations → {archived:[...], skipped:[{agent_id, reason}]}. Réversible via POST
    /api/sessions/<key>/restore.

    Id bruts acceptés aussi ; fonctionne pour TOUTES les natures, notamment "user"."""
    return jsonify(purge.archive_agents(_liste("keys")))


@sessions_bp.post("/api/sessions/purge-test")
def api_sessions_purge_test():
    """{dry?} — soft-delete des sessions CLI de test (titre 'test' + <=3 tours); dry=true → aperçu
    sans supprimer"""
    return jsonify(purge.purge_test_sessions(dry=bool(json_body(request).get("dry"))))


@sessions_bp.post("/api/sessions/<path:key>/restore")
def api_session_restore(key: str):
    """restaure une conversation archivée (retire du registre, rapatrie de la corbeille) → {ok,
    key} ; 404 `inconnu` si rien à restaurer"""
    if not purge.restore(key):
        raise Refus("inconnu", "rien à restaurer pour cette conversation", 404, key=key)
    return jsonify({"ok": True, "key": key})
