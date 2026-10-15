# [desc] Prédicats PURS du réveil des managers : issue d'un enfant lue dans `ticket.state`, signature des enfants, décision de réveil, digest. Extraits de `wake.py` (seuil ~200 lignes), ré-exportés par lui. [/desc]
from __future__ import annotations

from . import conflits, etat_ticket, wake_digest
from . import tickets as tickets_svc
from .distant import runs as runs_distants
from .fsm import etats


def is_manager_parent(parent: str) -> bool:
    """Un parent réveillable est un agent manager (agent_id), pas un tag dispatcher."""
    return bool(parent) and not parent.startswith("dispatcher:")


def _work_run(ticket: dict) -> dict | None:
    return next((r for r in ticket.get("runs") or [] if runs_distants.est_travail(r)), None)


def work_delivered(ticket: dict) -> bool:
    """L'enfant a rendu une réponse finale (livré, éventuellement intégré depuis)."""
    return ticket.get("state") == etats.DELIVERED or etat_ticket.integre(ticket)


def launch_failed(ticket: dict) -> bool:
    """Aucun agent n'a jamais démarré : un enfant TERMINÉ EN ÉCHEC, pas en cours."""
    return ticket.get("state") == etats.LAUNCH_FAILED


def launch_failure_label(ticket: dict) -> str:
    """Étiquette d'issue d'un lancement échoué. PURE et STABLE (lue par la signature)."""
    erreur = str((ticket.get("state_reason") or {}).get("message") or "")[:300]
    return ("ÉCHEC DE LANCEMENT — aucun agent n'a démarré, RIEN n'a été fait"
            + (f" : {erreur}" if erreur else ""))


def ticket_terminal(ticket: dict) -> bool:
    """L'enfant a une ISSUE pour le réveil du parent : plus rien ne bougera sans un geste."""
    return ticket.get("state") in etats.TERMINAUX_POUR_LE_PARENT


def _issue_arretee(ticket: dict) -> str:
    code = etat_ticket.code_raison(ticket)
    if ticket.get("state") == etats.IDLE_NO_DELIVERY:
        return f"ARRÊTÉ SANS LIVRER ({code or 'fin sans réponse finale'})"
    if code in ("interrupted", "killed", "arret_preparation"):
        return f"ARRÊTÉ ({code})"
    return "CRASHED"


def ticket_outcome(ticket: dict) -> str:
    """Étiquette d'issue d'un enfant pour le digest du parent — projection de `state`."""
    state = ticket.get("state")
    if state == etats.CLOSED:
        if etat_ticket.code_raison(ticket) == "integre":
            return "OK (mergé)"
        return "OK (éphémère, non mergé)" if ticket.get("ephemeral") else "CLOS (accepté)"
    if state == etats.ABANDONED:
        return "ABANDONNÉ"
    if state in (etats.STOPPED, etats.IDLE_NO_DELIVERY):
        travail = _work_run(ticket)
        if runs_distants.est_distant(travail) and not runs_distants.actif(travail):
            return runs_distants.etiquette(travail)
        return _issue_arretee(ticket)
    if state == etats.LAUNCH_FAILED:
        return launch_failure_label(ticket)
    if state == etats.CONFLICT:
        return conflits.libelle(ticket)
    if state == etats.DELIVERED and etat_ticket.code_raison(ticket) in ("merge_bloque", "merge_echoue"):
        return "MERGE BLOQUÉ (arbre principal sale) — à réintégrer"
    if state == etats.DELIVERED:
        travail = _work_run(ticket)
        if runs_distants.est_distant(travail):
            return runs_distants.etiquette(travail)
        return "travail LIVRÉ (non relu, non mergé) — conclusion dans le rapport de l'agent"
    return tickets_svc.derive_status(ticket)


def has_launched(ticket: dict) -> bool:
    """Un enfant lancé porte ≥1 run ; un orphelin (jamais lancé) est ignoré au réveil."""
    runs = ticket.get("runs")
    return isinstance(runs, list) and len(runs) > 0


def child_counts_for_wake(ticket: dict) -> bool:
    """L'enfant pèse dans le réveil : lancé, ou mort-né (lancement échoué)."""
    return has_launched(ticket) or launch_failed(ticket)


def child_pending_launch(ticket: dict) -> bool:
    """Enfant en cours de lancement : tant qu'il l'est, le parent n'est pas finalisé."""
    return ticket.get("state") == etats.PROVISIONING


def child_blocked_on_question(ticket: dict) -> bool:
    """Un enfant lancé qui ATTEND une réponse : sans lui, sa question resterait orpheline."""
    return has_launched(ticket) and ticket.get("state") == etats.AWAITING_INPUT


def children_signature(child_tickets: list[dict]) -> str:
    """Signature des enfants RÉELS : change quand un enfant a une NOUVELLE issue OU a clos un
    tour de plus (`turns`, incrémenté par la seule clôture d'un tour) — une ré-instruction qui
    re-livre la même issue réveille donc quand même. Pure."""
    return ";".join(f"{t['id']}:{ticket_outcome(t)}#t{wake_digest.run_turns(t)}"
                    for t in sorted(child_tickets, key=lambda t: t["id"])
                    if child_counts_for_wake(t))


def should_wake_parent(parent_finished: bool, child_tickets: list[dict],
                       last_signature: str | None, current_signature: str) -> bool:
    """Réveil (pur) : le manager a fini, ≥1 enfant réel, issues neuves, ET soit TOUS les
    enfants terminaux, soit ≥1 enfant BLOQUÉ sur une question (à qui répondre)."""
    if not parent_finished or any(child_pending_launch(t) for t in child_tickets):
        return False
    real = [t for t in child_tickets if child_counts_for_wake(t)]
    if not real:
        return False
    if not (all(ticket_terminal(t) for t in real) or any(child_blocked_on_question(t) for t in real)):
        return False
    return current_signature != last_signature


def build_wake_digest(child_tickets: list[dict]) -> str:
    from .wake_parents import digest_du_manager
    return digest_du_manager(child_tickets)
