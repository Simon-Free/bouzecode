# [desc] Nettoyage disque d'un ticket sur demande explicite : gardes vérifiées à l'instant (run vivant, travail non récolté), branche toujours gardée. [/desc]
"""`POST /api/projects/<slug>/tickets/<id>/cleanup` (spec ticketing §5.5, principe B9, constats C4/C15).

L'archivage ne détruit plus rien : il masque. Retirer le worktree d'un ticket est un geste
SÉPARÉ, refusé tant que :
  * un run est VIVANT — vérifié sur le vrai process (`runner.is_running`), au moment de l'action,
    jamais sur un état mis en cache (C4) : `run_vivant` ;
  * la récolte n'est pas propre : on commite le travail non commité JUSTE AVANT (geste demandé),
    et un arbre resté sale ou un merge inachevé interdit la destruction (C15) :
    `travail_non_recolte`.
La branche `agent/<ticket>` est TOUJOURS conservée : un ticket nettoyé reste intégrable depuis
elle (`integration.integrate_ticket` re-sort la branche), C5b."""
from __future__ import annotations

import logging
import threading

from bouzecode.web_v2.services.horodatage import maintenant_iso

from ...runtime.runner import agent_fiche, agent_vivacite
from . import delivery, tickets, worktrees
from .distant import runs as runs_distants
from .fsm import etats

_log = logging.getLogger(__name__)

EN_COURS = "en_cours"


def run_vivant(ticket: dict) -> str:
    """agent_id d'un run dont le process tourne À L'INSTANT (ou « lancement » si un spawn est
    en vol), "" sinon. Lit le vrai process, jamais `run['state']`."""
    if ticket.get("state") == etats.PROVISIONING:
        return "lancement"
    for run in ticket.get("runs") or []:
        if not isinstance(run, dict):
            continue
        if runs_distants.est_distant(run):
            if runs_distants.actif(run):
                return str(run.get("agent_id") or "distant")
            continue
        agent = agent_fiche.load_agent(str(run.get("agent_id") or ""))
        if agent is not None and agent_vivacite.is_running(agent):
            return agent.agent_id
    return ""


def preparer(slug: str, ticket: dict) -> dict:
    """Gardes + récolte, synchrones. Rend `{ok: True, a_retirer: bool}` ou un refus
    `{ok: False, code, error, ...}`. Persiste ce que la récolte a constaté."""
    meta = ticket.get("worktree")
    if not worktrees.dir_exists(meta):
        return {"ok": True, "a_retirer": False}
    vivant = run_vivant(ticket)
    if vivant:
        return {"ok": False, "code": "run_vivant", "agent_id": vivant,
                "error": f"un run est vivant ({vivant}) : arrête-le avant de nettoyer"}
    if not delivery.harvest_before_reclaiming(slug, ticket):
        meta = ticket.get("worktree") or {}
        bloque = worktrees.blocage_recolte(meta["worktree"]) if worktrees.dir_exists(meta) else None
        return {"ok": False, "code": "travail_non_recolte",
                "files": list(meta.get("non_commites") or []),
                "error": (bloque or {}).get("message") or
                "du travail reste non commité dans le worktree : rien n'a été détruit"}
    tickets._mutate(slug, ticket["id"], lambda t: t["worktree"].__setitem__("nettoyage", EN_COURS))
    return {"ok": True, "a_retirer": True}


def retirer(slug: str, ticket_id: str) -> bool:
    """Retire le worktree (branche gardée) après avoir REVÉRIFIÉ qu'aucun run n'a redémarré.
    Rend True si le worktree a été retiré."""
    ticket = tickets.get_ticket(slug, ticket_id)
    meta = (ticket or {}).get("worktree")
    if not isinstance(meta, dict):
        return False
    sale = worktrees.dir_exists(meta) and bool(worktrees.dirty_files(meta))
    if run_vivant(ticket) or sale:
        tickets._mutate(slug, ticket_id, lambda t: t["worktree"].pop("nettoyage", None))
        return False
    worktrees.reap(meta, delete_branch=False)

    def _acter(frais: dict) -> None:
        wt = frais["worktree"]
        wt.pop("nettoyage", None)
        wt["retire_at"] = _maintenant()
    tickets._mutate(slug, ticket_id, _acter)
    return True


def retirer_en_fond(slug: str, ticket_id: str) -> None:
    def _corps() -> None:
        try:
            retirer(slug, ticket_id)
        except Exception:  # noqa: BLE001 — journalisé ; l'état `nettoyage` reste visible
            _log.exception("nettoyage du ticket %s/%s en échec", slug, ticket_id)
    threading.Thread(target=_corps, daemon=True, name=f"cleanup-{ticket_id}").start()


def _maintenant() -> str:
    return maintenant_iso()


def constater_disparition(slug: str, ticket: dict) -> None:
    """C5b : un ticket dont le worktree a disparu du disque (nettoyé à la main, archivé avant L4)
    ne doit plus se dire présent : `worktree.retire_at` est posé ; l'intégration repartira de la
    branche (`integration.integrate_ticket`). No-op si l'arbre existe ou est déjà retiré."""
    meta = ticket.get("worktree")
    if not (isinstance(meta, dict) and meta.get("worktree")) or worktrees.dir_exists(meta):
        return
    if meta.get("retire_at"):
        return
    tickets.poser(slug, ticket, worktree={**meta, "retire_at": _maintenant()})


def nettoyer_le_projet(slug: str) -> list[str]:
    """Suppression d'un projet : nettoie chaque ticket qui passe les gardes (branche gardée).
    Un ticket refusé (run vivant, travail non récolté) garde son worktree. Rend les ids nettoyés."""
    nettoyes = []
    for ticket in tickets.list_tickets(slug, include_archived=True):
        if preparer(slug, ticket).get("a_retirer") and retirer(slug, ticket["id"]):
            nettoyes.append(ticket["id"])
    return nettoyes
