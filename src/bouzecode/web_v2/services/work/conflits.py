# [desc] Conflit de fusion d'un ticket : le watchdog CONSTATE sa résolution et le signale, sans jamais ré-intégrer. [/desc]
"""Ce qu'il advient d'un ticket dont `/integrate` a buté sur un conflit (spec §5.4, B4).

Avant le lot L4, le watchdog relançait le codeur pour résoudre (run `merge`), puis RE-MERGEAIT
tout seul quand il avait fini (`wake._reconcile_resolved_conflicts`). Plus rien de tout ça :
l'intégration renvoie le conflit, l'appelant relance qui il veut. Le watchdog se borne à
CONSTATER que le merge a été conclu dans le worktree (plus de merge en cours ni de marqueur) et
aucun run ne tourne : le ticket reste `conflict`, avec la raison `conflit_resolu` (« conflit
résolu, prêt à intégrer » — un sous-état, pas un état). Le fait remonte :
  * au parent manager, par son digest de réveil (`libelle`, lu par `wake.ticket_outcome`) ;
  * à l'humain, par un signalement, quand le ticket n'a pas de parent manager.
Personne n'intègre à sa place : c'est un nouvel appel à `/integrate`."""
from __future__ import annotations

from pathlib import Path

from . import etat_ticket, signalements, ticket_fsm, worktrees
from .fsm import etats

RESOLU = "conflit_resolu"


def libelle(ticket: dict) -> str:
    """Étiquette d'issue d'un ticket en conflit, pour le digest du parent ("" sinon). PURE et
    STABLE : `wake.children_signature` la lit à chaque tick."""
    if ticket.get("state") != etats.CONFLICT:
        return ""
    if etat_ticket.code_raison(ticket) == RESOLU:
        return "CONFLIT RÉSOLU — prêt à intégrer (rappelle integrate sur ce ticket)"
    fichiers = ", ".join(((ticket.get("integration") or {}).get("conflict_files") or [])[:6]) or "?"
    return (f"CONFLIT DE MERGE à résoudre (fichiers : {fichiers}) — relance l'agent pour le "
            "résoudre, puis réintègre")


def observer_resolution(slug: str, ticket: dict) -> bool:
    """Constate qu'un conflit a été résolu dans le worktree ; ne merge RIEN. True si la raison
    a changé. Appelé par le watchdog."""
    if ticket.get("state") != etats.CONFLICT or etat_ticket.code_raison(ticket) == RESOLU:
        return False
    wt = (ticket.get("worktree") or {}).get("worktree") or ""
    if not (wt and Path(wt).is_dir()) or worktrees.blocage_recolte(wt) is not None:
        return False  # merge pas conclu (MERGE_HEAD, marqueurs) : toujours en conflit
    ticket.update(ticket_fsm.appliquer(slug, ticket["id"], etats.CONFLICT_RESOLVED, "watchdog",
                                       code=RESOLU, message="conflit résolu, prêt à intégrer"))
    from . import wake  # import local : wake importe ce module
    if not wake.is_manager_parent(str(ticket.get("parent") or "")):
        signalements.creer(
            "info", f"Conflit résolu sur le ticket {ticket['id']} — prêt à intégrer",
            detail=f"« {ticket.get('title', '')} » ({slug}). Rien n'a été intégré d'office.",
            action_attendue=f"intégrer : POST /api/projects/{slug}/tickets/{ticket['id']}/integrate",
            ticket_slug=slug, ticket_id=ticket["id"])
    return True
