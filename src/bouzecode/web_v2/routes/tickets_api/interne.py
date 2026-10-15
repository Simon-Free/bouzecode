# [desc] Route INTERNE de fin de run (spec §6.5) : POST /internal/runs/{agent_id}/ended, appelée par le hook de l'agent avec SON jeton (X-Bouzecode-Run-Token), hors de l'API publique. [/desc]
from __future__ import annotations

from flask import Blueprint, request

from ...services.work.api_tickets import fin_de_run
from ...services.work.api_tickets.refus import Refus
from ._commun import corps, json

interne_bp = Blueprint("interne_api", __name__)


@interne_bp.post("/internal/runs/<agent_id>/ended")
def internal_run_ended(agent_id: str):
    """{close_reason, run_kind?} → 200 {advanced_to, state, state_reason} : le run se termine,
    `close_reasons` décide de l'issue. 403 `jeton_run_invalide`, 404 `run_inconnu` /
    `ticket_inconnu`, 415 hors application/json."""
    if request.content_length and request.mimetype != "application/json":
        raise Refus("type_contenu_invalide", "Corps attendu en application/json", 415)
    agent = fin_de_run.verifier_le_jeton(agent_id, request.headers.get(fin_de_run.EN_TETE_RUN, ""))
    payload = corps()
    return json(fin_de_run.terminer(agent.ticket_slug, agent.ticket_id, agent_id,
                                    str(payload.get("close_reason") or "")))
