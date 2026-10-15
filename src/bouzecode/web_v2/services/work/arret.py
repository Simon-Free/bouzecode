# [desc] Demande d'arrêt d'un agent (Fleet kill, arrêt depuis l'interface, MessageAgent arreter=true) : journalisée sur son ticket, elle interdit tout réveil automatique. [/desc]
"""Un agent dont on a demandé l'arrêt ne se relance pas tout seul.

Essai du 2026-09-25 : la racine 6bafe9cd a demandé à son enfant 40ea29e4 d'arrêter (« si tu
es redondant, arrête et rends ton rapport ») ; il a rendu sa FinalAnswer, puis le réveil
automatique (compte rendu de son propre enfant 85ce949a) l'a relancé pour 16 tours, jusqu'au
kill. La demande d'arrêt est désormais un ÉVÉNEMENT du journal du ticket (`arret_demande`,
levé par `arret_leve`), lu par `wake` avant de réveiller.
Un nouveau message explicite (MessageAgent sans arrêt) la lève : c'est une nouvelle consigne.
"""
from __future__ import annotations

from . import ticket_fsm, tickets
from .fsm import journal

ARRET_DEMANDE = journal.ARRET_DEMANDE


def demander(agent, par: str) -> None:
    """Pose la demande d'arrêt sur le ticket de `agent` (s'il en a un)."""
    slug, ticket_id = getattr(agent, "ticket_slug", ""), getattr(agent, "ticket_id", "")
    if not (slug and ticket_id):
        return
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is not None:
        poser(slug, ticket, par)


def poser(slug: str, ticket: dict, par: str) -> None:
    """La demande d'arrêt est un ÉVÉNEMENT du journal du ticket, pas un drapeau."""
    ticket_fsm.noter(slug, ticket["id"], journal.ARRET_DEMANDE, par, par=par)


def lever_pour(agent) -> None:
    """Retire la demande d'arrêt du ticket de `agent` (relance explicite par l'utilisateur)."""
    slug, ticket_id = getattr(agent, "ticket_slug", ""), getattr(agent, "ticket_id", "")
    if not (slug and ticket_id):
        return
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is not None:
        lever(slug, ticket)


def lever(slug: str, ticket: dict) -> None:
    if demande(ticket, slug):
        ticket_fsm.noter(slug, ticket["id"], journal.ARRET_LEVE)


def demande(ticket: dict | None, slug: str) -> bool:
    """La dernière consigne d'arrêt du journal est-elle une demande (non levée depuis) ?"""
    if not (ticket and ticket.get("id") and slug):
        return False
    with tickets._connect() as conn:
        dernier = journal.dernier(conn, slug, ticket["id"],
                                  (journal.ARRET_DEMANDE, journal.ARRET_LEVE))
    return bool(dernier and dernier["kind"] == journal.ARRET_DEMANDE)
