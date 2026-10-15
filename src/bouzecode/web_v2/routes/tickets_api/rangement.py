# [desc] Ranger un ticket (spec §5.5) : close / reopen (idempotents, worktree intact), PUT archived {archived} (masque, ne détruit rien), cleanup (202, retire le worktree, branche gardée). [/desc]
from __future__ import annotations

from flask import Blueprint

from ...schema import corps_attendu
from ...services.work import cloture_ticket, nettoyage, tickets
from ...services.work.api_tickets.refus import Refus
from ...services.work.etat_ticket import vue
from ...services.work.fsm import etats
from ._commun import corps, json, ticket_ou_refus

rangement_bp = Blueprint("tickets_rangement_api", __name__)


@rangement_bp.post("/api/projects/<slug>/tickets/<ticket_id>/close")
@corps_attendu(outcome="accepted|abandoned, requis", reason="texte",
               version="entier (verrou optimiste)")
def api_ticket_clore(slug: str, ticket_id: str):
    """{outcome: accepted|abandoned, reason?, version?} → 200 {state, closure_forced…}.
    Idempotent ; 400 `issue_inconnue`, 409 `transition_refusee` / `version_obsolete`."""
    ticket = ticket_ou_refus(slug, ticket_id)
    payload = corps()
    outcome = str(payload.get("outcome") or "")
    if outcome not in cloture_ticket.ISSUES:
        raise Refus("issue_inconnue", f"outcome doit valoir "
                    f"{' ou '.join(cloture_ticket.ISSUES)}", 400, outcome=outcome)
    return json(cloture_ticket.clore(slug, ticket, outcome, str(payload.get("reason") or ""),
                                     version=payload.get("version")))


@rangement_bp.post("/api/projects/<slug>/tickets/<ticket_id>/reopen")
@corps_attendu(version="entier (verrou optimiste)")
def api_ticket_rouvrir(slug: str, ticket_id: str):
    """→ 200 {state} : `delivered` (ou `created` sans run). Idempotent ; la trace d'une
    clôture forcée reste au journal (`closure_forced_reopened`)."""
    ticket = ticket_ou_refus(slug, ticket_id)
    return json(cloture_ticket.rouvrir(slug, ticket, version=corps().get("version")))


@rangement_bp.put("/api/projects/<slug>/tickets/<ticket_id>/archived")
@corps_attendu(archived="booléen, requis")
def api_ticket_archiver(slug: str, ticket_id: str):
    """{archived: true|false} → 200 {id, archived} : masque (ou remet) le ticket. Rien n'est
    détruit (le disque se libère par …/cleanup). Idempotent ; 409 `agent_actif`."""
    payload = corps()
    if not isinstance(payload.get("archived"), bool):
        raise Refus("champ_requis", "archived (booléen) requis", 400, champs=["archived"])
    return json(archiver(slug, ticket_id, payload["archived"]))


def archiver(slug: str, ticket_id: str, archived: bool) -> dict:
    ticket = ticket_ou_refus(slug, ticket_id)
    if archived and not ticket.get("archived"):
        if ticket.get("state") in etats.ACTIFS:
            raise Refus("agent_actif", "un agent travaille sur ce ticket : arrête-le avant de "
                        "l'archiver", 409, state=ticket.get("state"))
        tickets.archive_ticket(slug, ticket_id)
    elif not archived and ticket.get("archived"):
        nettoyage.constater_disparition(slug, tickets.unarchive_ticket(slug, ticket_id) or ticket)
    frais = tickets.get_ticket(slug, ticket_id) or ticket
    return {"ok": True, "id": ticket_id, "archived": bool(frais.get("archived")), **vue(frais)}


@rangement_bp.post("/api/projects/<slug>/tickets/<ticket_id>/cleanup")
def api_ticket_nettoyer(slug: str, ticket_id: str):
    """→ 202 {state: cleaning|removed|rien_a_nettoyer} : retire le worktree, branche GARDÉE.
    409 `run_vivant` / `travail_non_recolte` (gardes vérifiées à l'instant). `defer: false`
    retire avant de répondre."""
    ticket = ticket_ou_refus(slug, ticket_id)
    preparation = nettoyage.preparer(slug, ticket)
    if not preparation["ok"]:
        details = {k: v for k, v in preparation.items() if k not in ("ok", "code", "error")}
        raise Refus(preparation["code"], preparation["error"], 409, **details)
    if not preparation["a_retirer"]:
        return json({"ok": True, "id": ticket_id, "state": "rien_a_nettoyer"}, 202)
    if corps().get("defer", True):
        nettoyage.retirer_en_fond(slug, ticket_id)
        return json({"ok": True, "id": ticket_id, "state": "cleaning"}, 202)
    retire = nettoyage.retirer(slug, ticket_id)
    return json({"ok": True, "id": ticket_id, "state": "removed" if retire else "conserve"}, 202)
