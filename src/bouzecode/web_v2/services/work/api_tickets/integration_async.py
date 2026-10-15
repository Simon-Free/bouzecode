# [desc] POST …/integrate ASYNCHRONE (202) : gardes synchrones (agent actif, pas isolé, rien à intégrer sur les fichiers de code, conflit en cours), passage `integrating`, merge en fond → closed | conflict | delivered{merge_echoue}. [/desc]
"""Spec §5.4 (lot L5). La réponse part dès que le ticket est `integrating` ; un thread fait la
récolte et le merge sous le verrou de la base (`worktrees.integrate`), puis :

* `closed` (merge propre ; le worktree n'est retiré que si la récolte est PROPRE, C15) ;
* `conflict` avec `integration.conflict_files` — personne n'est relancé d'office ;
* retour à `delivered` avec `state_reason {code: merge_echoue, message, details.remede}`.

Les gardes, elles, sont synchrones et rendent un 409 : `agent_actif`, `pas_isole`,
`conflit_en_cours`, `rien_a_integrer` (aucun FICHIER DE CODE en avance sur la base, travail non
commité compris — `livraison.calculer`). Un worktree disparu n'est jamais « rien à intégrer » :
la branche est re-sortie et le merge part d'elle."""
from __future__ import annotations

import logging
import threading

from .. import integration, ticket_fsm, tickets, worktrees
from ..fsm import etats
from . import livraison
from .refus import Refus

_log = logging.getLogger(__name__)


def _gardes(ticket: dict) -> dict:
    if ticket.get("archived"):
        raise Refus("archive", "ticket archivé : désarchive-le d'abord", 409,
                    state=ticket.get("state"))
    if ticket.get("state") in etats.ACTIFS:
        raise Refus("agent_actif", "l'agent de travail tourne encore (ou une intégration est en "
                    "cours)", 409, state=ticket.get("state"))
    rep = livraison.reperes(ticket)
    if rep is None:
        raise Refus("pas_isole", "ticket non isolé (shared) : son travail est déjà dans le dépôt "
                    "principal, il n'y a rien à fusionner", 409, state=ticket.get("state"))
    if worktrees.dir_exists(rep["worktree"]):
        bloque = worktrees.blocage_recolte(rep["worktree"]["worktree"])
        if bloque is not None:
            raise Refus("conflit_en_cours", bloque["message"], 409, files=bloque["fichiers"],
                        state=ticket.get("state"), remede=bloque["message"])
    constat = livraison.calculer(ticket)
    if not livraison.travail_a_integrer(constat):
        raise Refus("rien_a_integrer", "aucun fichier de code en avance sur la base (les "
                    "fichiers de méta comme uv.lock, SYMBOLS.md, AGENTS.md ne comptent pas)", 409,
                    state=ticket.get("state"), delivery=constat)
    return rep["worktree"]


def _meta_vivante(slug: str, ticket: dict, meta: dict) -> dict | None:
    if worktrees.dir_exists(meta):
        return meta
    return integration._ressortir_la_branche(slug, ticket, meta)


def _en_fond(slug: str, ticket: dict, meta: dict) -> None:
    try:
        meta = _meta_vivante(slug, ticket, meta)
        if meta is None:
            ticket_fsm.appliquer(slug, ticket["id"], etats.INTEGRATE_FAILED, "serveur",
                                 code=integration.MERGE_ECHOUE, message="la branche du ticket "
                                 "n'a pas pu être re-sortie dans un worktree",
                                 details={"remede": "vérifie la branche agent/<ticket>"})
            return
        integration.executer(slug, ticket, meta)
    except Exception as exc:  # noqa: BLE001 — le ticket ne reste jamais `integrating`
        _log.exception("intégration du ticket %s/%s en échec", slug, ticket["id"])
        frais = tickets.get_ticket(slug, ticket["id"]) or {}
        if frais.get("state") == etats.INTEGRATING:
            ticket_fsm.appliquer(slug, ticket["id"], etats.INTEGRATE_FAILED, "serveur",
                                 code=integration.MERGE_ECHOUE, message=str(exc)[:500],
                                 details={"remede": "relis le journal du serveur puis relance"})
    finally:
        livraison.rafraichir(slug, tickets.get_ticket(slug, ticket["id"]) or ticket)


def integrer(slug: str, ticket: dict, attendre: bool = False) -> dict:
    """Gardes, `integrating`, puis le merge en fond. Rend le corps 202."""
    if ticket.get("ephemeral"):
        resultat = integration.finalize_ephemeral(slug, ticket)
        if not resultat.get("ok"):
            raise Refus(resultat.get("code") or "agent_actif", str(resultat.get("error")), 409)
        return {"ok": True, "state": ticket.get("state"), "ephemeral": True}
    meta = _gardes(ticket)
    integration._entrer(slug, ticket)  # (conflict →) delivered → integrating, sous verrou
    fil = threading.Thread(target=_en_fond, args=(slug, dict(ticket), meta), daemon=True,
                           name=f"integration-{ticket['id']}")
    fil.start()
    if attendre:
        fil.join(timeout=120)
    frais = tickets.get_ticket(slug, ticket["id"]) or ticket
    return {"ok": True, "state": frais.get("state"), "state_reason": frais.get("state_reason"),
            "integration": frais.get("integration"), "version": frais.get("version")}
