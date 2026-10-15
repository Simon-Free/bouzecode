# [desc] Ré-instruire l'agent d'un ticket : résolution ticket_id → (slug, ticket), et adaptateur `send_to_ticket_agent` vers LA remise unique (`api_tickets.remise`). [/desc]
"""Le manager ne connaît de ses enfants que leur ticket_id : `resolve_ticket` retrouve le
projet porteur. `send_to_ticket_agent` n'est plus qu'un ADAPTATEUR (forme de retour historique
`{ok, delivered, queued}` / `{ok: False, reason, code, error}`) de `api_tickets.remise.remettre`,
la seule implémentation de la remise d'un message (spec §5.2)."""
from __future__ import annotations

from typing import Any

from . import projects, tickets


def resolve_ticket(ticket_id: str) -> tuple[str, dict] | None:
    """Cherche le ticket dans tous les projets ouverts. Renvoie (slug, ticket) au 1er
    match, sinon None."""
    if not ticket_id:
        return None
    for project in projects.list_projects():
        ticket = tickets.get_ticket(project["slug"], ticket_id)
        if ticket is not None:
            return project["slug"], ticket
    return None


def send_to_ticket_agent(slug: str, ticket: dict, text: str,
                         interrompre: bool = False, arreter: bool = False) -> dict[str, Any]:
    """Remet `text` à l'agent du ticket (même agent, contexte gardé). Un agent en plein tour le
    lit à sa prochaine frontière de tour (`interrompre` coupe ce tour). Échec : `reason` =
    le code machine (`pas_d_agent`, `agent_missing`, `not_delivered`…)."""
    from .api_tickets import remise
    from .api_tickets.refus import Refus
    try:
        agent = remise.agent_du_ticket(ticket)
        return remise.remettre(agent, text, remise.INTERROMPRE if interrompre else remise.FILE,
                               arreter=arreter, du_ticket=(slug, ticket))
    except Refus as refus:  # forme historique : l'échec est un RÉSULTAT, pas une exception
        return {"ok": False, "reason": refus.code, "code": refus.status, "error": refus.message}
