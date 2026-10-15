# [desc] Garde-fou de CLÔTURE d'un manager : refuse « terminé » tant qu'un enfant n'a rien livré. [/desc]
"""Un manager ne peut pas être enregistré TERMINÉ tant qu'un de ses enfants a planté sans
rien livrer.

CAS RÉEL (ticket 642e1a3f, run manager 9d0789f2fdca, 2026-07-27) : cinq enfants dispatchés,
l'enfant `c08d9758` — le cœur fonctionnel de la demande utilisateur — mort avec
returncode=-1, session de 102 octets, ZÉRO bloc produit, ZÉRO fichier écrit. Le manager a
néanmoins rendu « VERDICT: OK » et `wake._finalize_noncoding_parent` l'a stampé `done=True`.
Rien ne l'a bloqué parce que l'état des enfants n'est consulté QUE via `wake.ticket_terminal`,
où `crashed` EST une issue terminale VALIDE : « tous les enfants sont terminaux » était donc
VRAI, et la seule barrière de qualité restante était le verdict AUTO-DÉCLARÉ du manager
(`verdict == "KO"`). L'utilisateur s'est vu annoncer une livraison complète.

PREUVE DE LIVRAISON — la MÊME que `workflow._is_crash` : un run porte `completed` (posé par
le hook `/completed`, ou reconstruit par `wake._reconcile_graceful_close` quand le callback a
été perdu) ou un `verdict`. C'est exactement ce qui séparait, dans le cas réel, les quatre
enfants livrés du cinquième.

COÛT : les prédicats sont PURS et sans AUCUNE I/O — ce garde-fou est évalué à chaque tick du
watchdog, il ne lit que les dicts d'enfants DÉJÀ chargés par `wake._children_by_parent()`. Il
n'écrit dans le store que lorsque l'ensemble des enfants bloquants CHANGE (une écriture, pas
une par tick).

TOLÉRANCE : un enfant archivé, clos ou abandonné à la main, ou mergé/fauché (la suite vit dans
un ticket de suivi) ne gèle JAMAIS son parent. Un enfant RELANCÉ cesse de bloquer dès son
premier tour clos proprement (`completed`).

TRACE : le blocage est la RAISON de l'état du parent (`delivered{cloture_bloquee}`, « Bloqué »
à l'écran), posée une fois et levée dès qu'il disparaît. PORTE DE SORTIE HUMAINE :
`POST /api/projects/<slug>/tickets/<id>/close` clôt en `closed{cloture_forcee}`, tracé au journal."""
from __future__ import annotations

from . import etat_ticket, reaper, ticket_fsm
from . import tickets as tickets_svc
from .fsm import etats

#: Code de `state_reason` du parent dont la clôture est refusée ; `details.enfants` = signature.
CLOSURE_BLOCKED_CODE = "cloture_bloquee"

_CRASHED_REASON = "planté sans aucune livraison (aucun run clos proprement)"
_LAUNCH_FAILED_REASON = "lancement échoué : aucun agent n'a démarré, la tâche n'a pas commencé"
_SILENT_REASON = "aucune livraison prouvée (aucun run clos proprement)"


def child_delivered_something(child: dict) -> bool:
    """L'enfant a-t-il une PREUVE de livraison ? (pur) — un run clos proprement (`completed`),
    ou un ticket livré / intégré."""
    if child.get("state") == etats.DELIVERED or etat_ticket.integre(child):
        return True
    return any(run.get("completed") for run in child.get("runs") or [] if isinstance(run, dict))


def child_launched(child: dict) -> bool:
    """Un enfant sans run n'a jamais démarré — SAUF un lancement échoué, qui compte : il est
    terminal pour le réveil, le parent ne doit pas se clore « terminé » par-dessus."""
    runs = child.get("runs")
    return (isinstance(runs, list) and len(runs) > 0) or child.get("state") == etats.LAUNCH_FAILED


def child_excused(child: dict) -> bool:
    """Dispensé de bloquer son parent (pur) : archivé, clos/abandonné (l'humain a statué), ou
    mergé et fauché (plus relançable, la suite vit dans un ticket de suivi)."""
    if child.get("archived") or child.get("state") in etats.CLOS:
        return True
    return reaper.is_resume_blocked(child) is not None


def blocking_children(child_tickets: list[dict]) -> list[tuple[str, str]]:
    """Les enfants qui INTERDISENT la clôture du parent : [(id, raison)]. PUR, zéro I/O."""
    blocking: list[tuple[str, str]] = []
    for child in child_tickets:
        if not isinstance(child, dict) or not child.get("id"):
            continue
        if not child_launched(child) or child_excused(child) or child_delivered_something(child):
            continue
        if child.get("state") == etats.LAUNCH_FAILED:
            reason = _LAUNCH_FAILED_REASON
        else:
            reason = _CRASHED_REASON if child.get("state") == etats.STOPPED else _SILENT_REASON
        blocking.append((child["id"], reason))
    return blocking


def block_signature(blocking: list[tuple[str, str]]) -> str:
    """Signature stable de la situation de blocage (ids triés) : tracée une fois."""
    return ";".join(sorted(child_id for child_id, _ in blocking))


def block_comment(slug: str, ticket_id: str, blocking: list[tuple[str, str]]) -> str:
    """Le commentaire de trace : nomme CHAQUE enfant fautif, la raison, et les deux sorties."""
    lines = ["⛔ Clôture BLOQUÉE : ce manager ne peut pas être enregistré « terminé » tant "
             "que ces enfants n'ont rien livré :"]
    lines += [f"- enfant {child_id} : {reason}" for child_id, reason in blocking]
    lines += [
        "Relance l'enfant (bouton Relancer sur son ticket) s'il reste du travail, ou "
        "archive-le si son travail est abandonné ou repris par un autre ticket.",
        f"Pour clore malgré tout EN CONNAISSANCE DE CAUSE : POST "
        f"/api/projects/{slug}/tickets/{ticket_id}/close {{outcome: accepted}} (bouton Terminé) — "
        "la clôture forcée sera tracée.",
    ]
    return "\n".join(lines)


def _signature_posee(ticket: dict) -> str:
    if etat_ticket.code_raison(ticket) != CLOSURE_BLOCKED_CODE:
        return ""
    return str(((ticket.get("state_reason") or {}).get("details") or {}).get("enfants") or "")


def _record_block(slug: str, ticket: dict, blocking: list[tuple[str, str]]) -> bool:
    """Trace le blocage (raison de l'état + commentaire), SEULEMENT quand il a changé."""
    signature = block_signature(blocking)
    if _signature_posee(ticket) == signature:
        return False
    frais = ticket_fsm.motiver(slug, ticket["id"], CLOSURE_BLOCKED_CODE,
                               "un enfant n'a rien livré", enfants=signature)
    tickets_svc.add_comment(slug, ticket, block_comment(slug, ticket["id"], blocking), False)
    if frais is not None:
        ticket.update(state_reason=frais.get("state_reason"), version=frais["version"])
    return True


def _clear_block(slug: str, ticket: dict) -> bool:
    """Lève la trace de blocage : tous les enfants ont livré depuis."""
    if not _signature_posee(ticket):
        return False
    frais = ticket_fsm.motiver(slug, ticket["id"], None)
    if frais is not None:
        ticket.update(state_reason=frais.get("state_reason"), version=frais["version"])
    return True


def refuse_closure(slug: str, parent: dict, child_tickets: list[dict]) -> list[tuple[str, str]]:
    """LE point d'entrée du garde-fou : les enfants bloquants ([] = clôture permise), et la
    trace visible sur le parent (posée une fois, levée dès que le blocage disparaît). Un parent
    qui n'est pas LIVRÉ (déjà clos — y compris par une clôture forcée —, ou encore au travail)
    n'a pas de clôture à garder."""
    if parent.get("state") != etats.DELIVERED:
        return []
    blocking = blocking_children(child_tickets)
    if blocking:
        _record_block(slug, parent, blocking)
    else:
        _clear_block(slug, parent)
    return blocking


def force_closure(slug: str, ticket: dict) -> str:
    """Porte de sortie EXPLICITE de l'humain (`POST …/close`) : rend la signature forcée ("" si
    rien n'était bloqué) et trace la décision au journal ; l'appelant clôt en `cloture_forcee`."""
    signature = _signature_posee(ticket)
    if signature:
        tickets_svc.add_comment(
            slug, ticket, "⚠️ Clôture FORCÉE à la main alors que ces enfants n'avaient rien "
            f"livré : {signature.replace(';', ', ')}. Décision explicite de l'utilisateur.", False)
    return signature
