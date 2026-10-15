# [desc] La FIN d'un run traduite en transition de ticket (livré, non livré, arrêté, en attente des enfants), y compris le crash démenti par un hook tardif. Appelé par le hook de fin d'agent et par le watchdog (`constats`). [/desc]
"""Extrait de `constats.py` : `fin_de_run`, le seul chemin par lequel un run se termine.

`close_reasons.issue_de_fin` est la SEULE table qui dit livré / non livré / arrêté (C14).
Les noms publics restent importables depuis `constats` (ré-export)."""
from __future__ import annotations

from ... import close_reasons
from . import _persistence, refus_modele, ticket_fsm
from .fsm import etats
from .runs_ticket import mark_run_completed


def enfants_actifs(agent_id: str) -> bool:
    """Un ticket dont `agent_id` est le parent est-il encore en vol (lancement, run, merge) ?"""
    marques = ",".join("?" * len(etats.ACTIFS))
    with _persistence._connect() as conn:
        ligne = conn.execute(
            "SELECT 1 FROM tickets WHERE json_extract(data, '$.parent')=? AND"
            f" json_extract(data, '$.state') IN ({marques}) LIMIT 1",
            (agent_id, *sorted(etats.ACTIFS))).fetchone()
    return ligne is not None


def _attend_ses_enfants(agent_id: str) -> bool:
    """Tout agent qui délègue (pas seulement un profil manager) et clôt son tour pendant que
    ses enfants travaillent — ou ont fini APRÈS son tour, sans qu'il les ait relus — n'a pas
    fini : il sera réveillé par leur compte rendu. Instants des process, pas des constats."""
    from .relecture_enfants import enfants_non_relus
    return enfants_non_relus(agent_id, enfants_actifs(agent_id))


def fin_de_run(slug: str, ticket_id: str, agent_id: str, close_reason: str,
               final_answer: bool = False, actor: str = "hook") -> str | None:
    """Le run de `agent_id` s'est terminé sur `close_reason` : livré, non livré ou arrêté, selon
    `close_reasons.issue_de_fin`. Un manager qui clôt son tour pendant que ses enfants tournent
    reste `running` (run `awaiting_children`) : il sera réveillé. Idempotent : un ticket qui
    n'est plus en vol n'est pas touché. Rend le nouvel état (None si rien n'a bougé)."""
    ticket = _persistence._load_one(slug, ticket_id)
    issue, code = close_reasons.issue_de_fin(close_reason, final_answer)
    if ticket is not None and _crash_dementi(ticket, agent_id, issue):
        return _livre_apres_coup(slug, ticket_id, agent_id, close_reason, code, final_answer, actor)
    if ticket is None or ticket["state"] not in (etats.RUNNING, etats.AWAITING_INPUT):
        return None
    if ticket["state"] == etats.AWAITING_INPUT:
        ticket = ticket_fsm.appliquer(slug, ticket_id, etats.ANSWERED, actor, agent_id=agent_id)
    if issue != etats.STOPPED and _attend_ses_enfants(agent_id):
        return ticket_fsm.appliquer(slug, ticket_id, etats.AWAITING_CHILDREN, actor,
                                    agent_id=agent_id, close_reason=close_reason)["state"]
    if issue == etats.DELIVERED:  # `completed` = preuve de livraison (garde-fou de clôture)
        mark_run_completed(slug, ticket, agent_id)
    if issue == etats.STOPPED:
        evenement = etats.STOP if code == "interrupted" else etats.CRASHED
        return ticket_fsm.appliquer(slug, ticket_id, evenement, actor, agent_id=agent_id,
                                    code=code, close_reason=close_reason)["state"]
    frais = ticket_fsm.appliquer(slug, ticket_id, etats.RUN_ENDED, actor, agent_id=agent_id,
                                 delivered=issue == etats.DELIVERED, code=code,
                                 close_reason=close_reason, final_answer=final_answer)
    if close_reason == refus_modele.REFUS_MODELE:  # ni livré ni planté : dire quoi faire
        refus_modele.signaler(slug, frais, agent_id)
    if frais["state"] == etats.DELIVERED:
        from . import delivery, integration  # constat de livraison, jamais un commit
        from .api_tickets import livraison
        delivery.record_delivery(slug, frais)
        integration.conclure_l_auto_integration(slug, frais)
        livraison.rafraichir(slug, _persistence._load_one(slug, ticket_id) or frais)
    return frais["state"]


def _crash_dementi(ticket: dict, agent_id: str, issue: str) -> bool:
    """Le watchdog a classé ce run `stopped{crashed}` (process disparu), puis son hook de fin
    arrive et PROUVE une réponse finale : le constat de crash était faux (lot L5, limite (a))."""
    from .etat_ticket import code_raison
    dernier = next((r for r in ticket.get("runs") or [] if isinstance(r, dict)), None) or {}
    return (issue == etats.DELIVERED and ticket["state"] == etats.STOPPED
            and code_raison(ticket) == "crashed" and dernier.get("agent_id") == agent_id)


def _livre_apres_coup(slug: str, ticket_id: str, agent_id: str, close_reason: str, code: str,
                      final_answer: bool, actor: str) -> str:
    frais = ticket_fsm.appliquer(slug, ticket_id, etats.RUN_ENDED, actor, agent_id=agent_id,
                                 delivered=True, code=code, close_reason=close_reason,
                                 final_answer=final_answer, crash_dementi=True)
    from . import delivery
    delivery.record_delivery(slug, frais)
    return frais["state"]
