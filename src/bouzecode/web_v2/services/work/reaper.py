# [desc] Faucheur (GC) des bacs à sable de tickets INTÉGRÉS ou éphémères clos, jamais d'un arbre sale ni sous un agent vivant. [/desc]
"""GC du cycle de vie des tickets : le seul retrait de worktree qui n'est pas demandé à la main.

On ne retire le worktree (working tree + venv, coûteux en disque) que d'un ticket CLOS par un
merge (`closed{integre}`) ou d'un ticket éphémère arrivé au bout — branche supprimée avec,
et seulement si l'arbre est propre pour un ticket mergé (B9, C15). Tout le reste est REPRENABLE :
on conserve TOUT ; le retrait d'un worktree non mergé est le geste explicite `…/cleanup`.

L'idempotence ne tient plus à un drapeau `reaped` : un worktree retiré porte `retire_at` (fait
physique du bac à sable, pas un état du ticket). Prédicats purs (`should_reap`,
`should_delete_branch`) ; `reap_ticket` est le seul à toucher le disque."""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import etat_ticket, tickets, worktrees
from .fsm import etats


def _fauchable(ticket: dict) -> bool:
    """Mergé, ou bac à sable de test (éphémère) arrivé au bout : clos, abandonné ou planté."""
    return etat_ticket.integre(ticket) or (
        bool(ticket.get("ephemeral")) and ticket.get("state") in (etats.STOPPED, *etats.CLOS))


def should_delete_branch(ticket: dict) -> bool:
    """La branche `agent/<ticket>` part avec le worktree d'un travail mergé ou jetable."""
    return _fauchable(ticket)


def should_reap(ticket: dict) -> bool:
    """Faut-il faucher ce ticket ? Vrai s'il est clos par un merge (ou éphémère) et que son
    worktree n'a pas encore été retiré. Pur."""
    meta = ticket.get("worktree")
    if not (isinstance(meta, dict) and meta.get("worktree")) or meta.get("retire_at"):
        return False
    return _fauchable(ticket)


def is_resume_blocked(ticket: dict) -> str | None:
    """Message actionnable si l'agent d'un ticket NE DOIT PLUS être relancé : mergé et worktree
    retiré, il renaîtrait dans un dossier fantôme. None sinon. Pur."""
    if etat_ticket.integre(ticket) and (ticket.get("worktree") or {}).get("retire_at"):
        return ("ticket déjà mergé/reapé — crée un ticket de suivi "
                "(le worktree a été nettoyé)")
    return None


def _arbre_sale(meta) -> bool:
    """Le worktree existe-t-il avec du travail NON COMMITÉ ? (B9 : jamais détruit)"""
    return worktrees.dir_exists(meta) and bool(worktrees.dirty_files(meta))


def reap_ticket(slug: str, ticket: dict) -> bool:
    """Fauche un ticket dont le travail est RÉELLEMENT FINI : retire le worktree (+ la
    branche) et note `worktree.retire_at`. No-op si non fauchable, déjà fauché, ou — pour un
    ticket mergé — arbre SALE : la récolte n'est pas propre, on ne détruit rien (C15)."""
    if not should_reap(ticket):
        return False
    meta = ticket["worktree"]
    if not ticket.get("ephemeral") and _arbre_sale(meta):
        return False
    worktrees.reap(meta, delete_branch=should_delete_branch(ticket))
    tickets.poser(slug, ticket, worktree={**meta, "retire_at": maintenant_iso()})
    return True
