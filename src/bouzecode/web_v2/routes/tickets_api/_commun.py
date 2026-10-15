# [desc] Outils partagés des routes de l'API tickets : corps JSON lu une fois, ticket ou 404/409 archivé, réponse JSON lisible. [/desc]
from __future__ import annotations

import json as _json

from flask import Response, g, request

from ...services.work import tickets
from ...services.work.api_tickets.refus import Refus
from .._body import json_body

def corps() -> dict:
    """Le corps JSON de la requête, lu UNE fois (`json_body` consomme le flux)."""
    if "corps_json" not in g:
        g.corps_json = json_body(request)
    return g.corps_json


def ticket_ou_refus(slug: str, ticket_id: str, geste: bool = False) -> dict:
    """Le ticket, ou 404 `ticket_inconnu` (un ticket d'un projet retiré du registre reste
    lisible et rangeable). `geste` : un ticket ARCHIVÉ n'accepte que les lectures, la
    désarchivage, la clôture et le nettoyage (409 `archive`, spec §4)."""
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None:
        raise Refus("ticket_inconnu", f"ticket inconnu : {ticket_id}", 404, ticket_id=ticket_id)
    if geste and ticket.get("archived"):
        raise Refus("archive", "ticket archivé : il n'accepte que les lectures et la "
                    "désarchivage (PUT …/archived {archived:false})", 409,
                    state=ticket.get("state"))
    return ticket


def json(donnees, status: int = 200) -> Response:
    """Réponse JSON indentée (lisible par un humain qui lit l'API au terminal), UTF-8 brut."""
    return Response(_json.dumps(donnees, indent=2, ensure_ascii=False), status=status,
                    mimetype="application/json")

