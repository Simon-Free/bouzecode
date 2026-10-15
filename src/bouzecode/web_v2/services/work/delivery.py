# [desc] Livraison d'un agent : constat en fin de run (sans commit), récolte seulement sur geste explicite, arbre jamais détruit sale ; ce qui reste en péril devient la raison de l'état. [/desc]
"""Le chaînon entre « l'agent a fini » et « son travail existe quelque part ».

`worktrees.harvest` est le SEUL geste qui commite le travail non commité d'un agent sur sa
branche `agent/<ticket>`. Il n'est jamais joué d'office (principe B4) : seulement juste avant
un geste DEMANDÉ, aucun run vivant — intégration, nettoyage, relance re-isolée.

En fin de run livré, on CONSTATE seulement (`record_delivery`, appelé par `constats` quand le
ticket passe `delivered`) : tête de la branche et fichiers laissés non commités
(`worktree.non_commites`, information pour qui juge la livraison).

L'ANOMALIE, c'est une récolte demandée qui échoue (index verrouillé, merge inachevé) : les
fichiers en péril restent dans `worktree.non_commites` et, sur un ticket livré, la raison de
l'état devient `livraison_non_commitee` (« Bloqué » à l'écran)."""
from __future__ import annotations

from . import etat_ticket, ticket_fsm, worktrees
from . import tickets as tickets_svc
from .fsm import etats

_MAX_FLAGGED_FILES = 20  # le constat nomme les fichiers en péril, il n'archive pas un diff
NON_COMMITEE = "livraison_non_commitee"

#  Posé sur le run quand sa livraison a été constatée ; un nouveau run repart sans.
CONSTATEE = "delivery_checked"


def work_run(ticket: dict) -> dict | None:
    """Le run de TRAVAIL le plus récent du ticket (c'est lui qui produit du code)."""
    return next((r for r in ticket.get("runs") or []
                 if isinstance(r, dict) and r.get("kind") == "work"), None)


def bac_a_sable(ticket: dict) -> dict | None:
    """Le worktree du ticket s'il existe encore (ni ticket `shared`, ni worktree retiré)."""
    meta = ticket.get("worktree")
    if not (isinstance(meta, dict) and meta.get("worktree") and meta.get("branch")):
        return None
    return None if meta.get("retire_at") else meta


def delivery_at_risk(ticket: dict) -> bool:
    """PUR : une récolte DEMANDÉE a-t-elle laissé du travail non commité ?"""
    return etat_ticket.code_raison(ticket) == NON_COMMITEE


def record_delivery(slug: str, ticket: dict) -> None:
    """CONSTAT (aucun commit) de ce que l'agent laisse dans son worktree. Idempotent."""
    meta, run = bac_a_sable(ticket), work_run(ticket)
    if meta is None or run is None or run.get(CONSTATEE):
        return
    constat: dict = {}
    if worktrees.dir_exists(meta):
        constat = {"delivered_head": worktrees.head_of(meta),
                   "non_commites": worktrees.dirty_files(meta)[:_MAX_FLAGGED_FILES]}

    def _apply(frais: dict) -> None:
        if isinstance(frais.get("worktree"), dict):
            frais["worktree"].update(constat)
        for candidat in frais.get("runs") or []:
            if candidat.get("agent_id") == run["agent_id"]:
                candidat[CONSTATEE] = True
    frais = tickets_svc._mutate(slug, ticket["id"], _apply)
    if frais is not None:
        ticket.clear()
        ticket.update(frais)


def noter_recolte(slug: str, ticket: dict, recolte: dict) -> None:
    """Persiste ce qu'une récolte DEMANDÉE a laissé : tête livrée, fichiers en péril, et — sur
    un ticket livré — la raison `livraison_non_commitee` (posée ou levée)."""
    restes = list(recolte.get("dirty") or [])[:_MAX_FLAGGED_FILES]
    meta = dict(ticket.get("worktree") or {}, delivered_head=recolte.get("head", ""),
                non_commites=restes)
    tickets_svc.poser(slug, ticket, worktree=meta)
    bloque = (recolte.get("bloque") or {}).get("message") or ""
    if ticket.get("state") != etats.DELIVERED:
        return
    if restes or bloque:
        frais = ticket_fsm.motiver(slug, ticket["id"], NON_COMMITEE, bloque, files=restes)
    elif delivery_at_risk(ticket):
        frais = ticket_fsm.motiver(slug, ticket["id"], None)
    else:
        return
    if frais is not None:
        ticket.update(state_reason=frais.get("state_reason"), version=frais["version"])


def reopen_for_new_work(slug: str, ticket_id: str) -> None:
    """Un agent RELANCÉ sur le même run (message, réponse) va produire du travail NEUF : sa
    livraison sera constatée à nouveau. Une vraie relance repart d'un run neuf. No-op sinon."""
    if not (slug and ticket_id):
        return
    ticket = tickets_svc.get_ticket(slug, ticket_id)
    run = work_run(ticket) if ticket else None
    if not (run and run.get(CONSTATEE)):
        return

    def _rouvrir(frais: dict) -> None:
        for candidat in frais.get("runs") or []:
            if candidat.get("agent_id") == run["agent_id"]:
                candidat.pop(CONSTATEE, None)
    tickets_svc._mutate(slug, ticket_id, _rouvrir)


def harvest_before_reclaiming(slug: str, ticket: dict) -> bool:
    """Récolte JUSTE AVANT de retirer un worktree, sur un geste demandé (nettoyage, relance
    re-isolée) : True seulement si plus rien n'est en péril. False — et l'appelant ne détruit
    RIEN — quand la récolte est suspendue (merge inachevé) ou laisse l'arbre SALE (C15)."""
    meta = bac_a_sable(ticket)
    if meta is None or etat_ticket.integre(ticket) or not worktrees.dir_exists(meta):
        return True  # déjà mergé, ou plus d'arbre : plus rien à sauver ici
    recolte = worktrees.harvest(meta, ticket.get("title", ""))
    noter_recolte(slug, ticket, recolte)
    return not recolte.get("bloque") and not recolte.get("dirty")
