# [desc] `bouzecode tickets suivre` : attend la fin d'un ticket en affichant son journal ; sans serveur, joue lui-même le pas du watchdog (constats locaux, suivre/recuperer Rundeck, file de messages) sous le verrou de référence. [/desc]
"""Un pas de suivi = ce que `wake.tick` fait pour CE ticket, rien de plus :

* `distant.suivi.suivre_tickets` (exécution Rundeck : `suivre` à cadence ≥ 30 s, `recuperer` à
  la fin, run clos) ;
* `constats.constater` (agent local : question, fin de run lue dans sa session, process mort) ;
* `file_messages.livrer_prets` (un message mis en file pendant un tour est remis au repos).

Le pas n'agit que s'il obtient le verrou du serveur de référence (`reference.pour_un_pas_cli`) ;
sinon un serveur vit et son watchdog fait ce travail : la CLI se contente de lire. Les parents
(managers) ne sont PAS réveillés ici : c'est le rôle du serveur.

Codes de sortie (alignés sur `ui/cloture_cli.py`) : 0 livré (ou intégré) ; 3 refus du modèle ;
4 fin sans livraison (fin forcée, conflit, abandon, jamais lancé) ; 5 arrêté, planté, lancement
échoué ; 6 l'agent attend une réponse (`tickets message`) ; 7 délai `--delai` écoulé, ticket
toujours en vol ; 130 suivi interrompu (Ctrl+C : l'agent, lui, continue).
"""
from __future__ import annotations

import time

from ..cloture_cli import EXIT_FIN_FORCEE, EXIT_LIVRE, EXIT_MORT_EN_VOL, code_de_sortie

EXIT_QUESTION = 6
EXIT_DELAI = 7
EXIT_INTERROMPU = 130


def code_de_fin(ticket: dict) -> int | None:
    """Le code de sortie d'un ticket qui ne bougera plus seul ; None tant qu'il est en vol."""
    from bouzecode.web_v2.services.work.etat_ticket import code_raison
    from bouzecode.web_v2.services.work.fsm import etats
    etat = ticket.get("state")
    if etat == etats.AWAITING_INPUT:
        return EXIT_QUESTION
    if etat in etats.ACTIFS:
        return None
    if etat in (etats.DELIVERED, etats.CLOSED):
        return EXIT_LIVRE
    if etat == etats.IDLE_NO_DELIVERY:
        return code_de_sortie(code_raison(ticket) or "")
    if etat in (etats.CONFLICT, etats.ABANDONED, etats.CREATED):
        return EXIT_FIN_FORCEE
    return EXIT_MORT_EN_VOL


def un_pas(slug: str, ticket_id: str) -> dict | None:
    """Un pas du watchdog sur ce ticket (si aucun serveur ne le tient), puis l'état relu."""
    from bouzecode.web_v2 import reference
    from bouzecode.web_v2.services.work import constats, file_messages, tickets
    from bouzecode.web_v2.services.work.distant import suivi as suivi_distant
    with reference.pour_un_pas_cli() as seul:
        ticket = tickets.get_ticket(slug, ticket_id)
        if seul and ticket is not None and constats.a_constater(ticket):
            suivi_distant.suivre_tickets(slug, [ticket])
            frais = tickets.get_ticket(slug, ticket_id) or ticket
            if constats.a_constater(frais):
                constats.constater(slug, frais)
            file_messages.livrer_prets()
    return tickets.get_ticket(slug, ticket_id)


def _nouveaux_evenements(slug: str, ticket_id: str, depuis: int) -> list[dict]:
    from bouzecode.web_v2.services.work import ticket_fsm
    return ticket_fsm.events(slug, ticket_id, depuis)


def suivre(slug: str, ticket_id: str, ecrire, intervalle: float = 5.0,
           delai: float | None = None, horloge=time.monotonic, dormir=time.sleep) -> dict:
    """Suit jusqu'à la fin ; `ecrire(evenement)` reçoit chaque événement du journal. Rend
    `{code, ticket}`. `horloge`/`dormir` : injectables (tests)."""
    from .gestes import ticket as ticket_ou_erreur
    ticket = ticket_ou_erreur(slug, ticket_id)
    vus = 0
    debut = horloge()
    while True:
        for evenement in _nouveaux_evenements(slug, ticket_id, vus):
            vus = max(vus, int(evenement.get("seq") or 0))
            ecrire(evenement)
        code = code_de_fin(ticket)
        if code is not None:
            return {"code": code, "ticket": ticket}
        if delai is not None and horloge() - debut >= delai:
            return {"code": EXIT_DELAI, "ticket": ticket}
        dormir(intervalle)
        ticket = un_pas(slug, ticket_id) or ticket
