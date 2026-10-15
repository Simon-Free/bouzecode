# [desc] Livraison et intégration (spec §5.4, lot L5) : delivery/refresh, harvest (409 run vivant), integrate ASYNCHRONE (202), diff de la branche du ticket, occupation d'un projet. [/desc]
from __future__ import annotations

from flask import Blueprint

from ...services.work.api_tickets import creation, integration_async, lectures, livraison
from ...services.work.api_tickets.refus import Refus
from ._commun import corps, json, ticket_ou_refus

livraison_bp = Blueprint("tickets_livraison_api", __name__)


@livraison_bp.post("/api/projects/<slug>/tickets/<ticket_id>/delivery/refresh")
def api_ticket_livraison(slug: str, ticket_id: str):
    """→ 200 {delivery: {head, commits_ahead, code_files_ahead, dirty, dirty_code_files,
    checked_at}} : recalcule ce que porte la branche (lecture git) et le persiste. 409
    `pas_isole` pour un ticket shared."""
    ticket = ticket_ou_refus(slug, ticket_id)
    constat = livraison.rafraichir(slug, ticket)
    if constat is None:
        raise Refus("pas_isole", "ticket non isolé : pas de branche à mesurer", 409,
                    state=ticket.get("state"))
    return json({"delivery": constat})


@livraison_bp.post("/api/projects/<slug>/tickets/<ticket_id>/harvest")
def api_ticket_recolter(slug: str, ticket_id: str):
    """→ 200 {commit?, dirty[]} : commite le travail non commité du worktree. 409 `run_vivant`,
    `pas_isole`, `conflit_en_cours`."""
    return json(livraison.recolter(slug, ticket_ou_refus(slug, ticket_id, geste=True)))


@livraison_bp.post("/api/projects/<slug>/tickets/<ticket_id>/integrate")
def api_ticket_integrer(slug: str, ticket_id: str):
    """→ 202 {state: "integrating"} : merge EN FOND, sous le verrou de la base → `closed` |
    `conflict {integration.conflict_files}` | `delivered {state_reason: merge_echoue, remede}`.
    409 `rien_a_integrer` (aucun fichier de code en avance) / `agent_actif` /
    `conflit_en_cours` / `pas_isole` / `transition_refusee`. `wait: true` attend l'issue."""
    ticket = ticket_ou_refus(slug, ticket_id, geste=True)
    return json(integration_async.integrer(slug, ticket, attendre=bool(corps().get("wait"))), 202)


@livraison_bp.get("/api/projects/<slug>/tickets/<ticket_id>/diff")
def api_ticket_diff(slug: str, ticket_id: str):
    """{branch, base, commits:[{sha, subject}], files:[{status, path, code}], isolated} : la
    BRANCHE du ticket contre sa base (lecture git). 504 `git_trop_lent`."""
    return json(livraison.diff(ticket_ou_refus(slug, ticket_id)))


@livraison_bp.get("/api/projects/<slug>/occupation")
def api_projet_occupation(slug: str):
    """{runs:[{agent_id, ticket_id, state, isolation, cwd, branch}]} : qui écrit où dans ce
    projet — ce qu'un manager lit pour choisir l'isolation de son enfant. LECTURE PURE."""
    return json(lectures.occupation(slug, creation.projet(slug)))
