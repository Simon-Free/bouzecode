# [desc] API des décisions du Bureau : lister les cartes ouvertes, répondre, relancer une livraison. [/desc]
"""§7 du SPEC_BUREAU_WEBV2 : `POST /api/decisions/<id>/answer`.

ENREGISTRER la réponse et la TRANSMETTRE à l'agent sont deux actes distincts. Répondre 409 ou
500 parce que l'agent est injoignable ferait perdre la décision de l'humain, qu'il faudrait
re-saisir : la réponse est donc persistée d'abord, puis la livraison est tentée et son résultat
rendu DANS le corps (`delivery`), jamais dans le code HTTP. `POST /retry` existe pour ça.

Seuls le store peut refuser : 404 si la carte n'existe pas, 409 si elle a déjà une réponse.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ...services.work import decisions, messaging, tickets
from .._errors import erreur

_log = logging.getLogger(__name__)

decisions_bp = Blueprint("decisions_api", __name__)

_REFUS = {"not_found": (404, "carte de décision inconnue"),
          "already_answered": (409, "cette décision a déjà une réponse")}


def _refus(statut: str, **details):
    status, message = _REFUS[statut]
    return erreur(statut, message, status, **details)


def _message(row: dict) -> str:
    """Le texte envoyé à l'agent : sa question, puis la réponse humaine.

    On rappelle la question parce que l'agent peut avoir attendu des jours : un simple
    « integrer » sans son contexte est indéchiffrable dans un fil de conversation."""
    choix = row.get("answer_key") or ""
    texte = row.get("answer_text") or ""
    reponse = " — ".join(part for part in (choix, texte) if part) or "(sans réponse)"
    return f"Réponse du Bureau à « {row.get('question') or ''} » : {reponse}"


def _deliver(row: dict) -> dict:
    """Transmet la réponse à l'agent du ticket et TRACE l'issue dans `delivery`.

    Rend toujours un dict lisible par le front : `state` (delivered|failed|n_a) et, en cas
    d'échec, le `reason` MACHINE de `send_to_ticket_agent` (no_work_run / agent_missing /
    running / not_delivered) — de quoi savoir s'il faut réessayer ou restaurer une fiche."""
    slug = row.get("project_slug") or ""
    ticket_id = str(row.get("ticket_id") or "")
    if not (slug and ticket_id):
        # Carte dérivée d'une situation sans agent à prévenir (ex. décision purement humaine) :
        # il n'y a RIEN à livrer, et le dire « échoué » ferait clignoter une alerte à tort.
        decisions.mark_delivery(row["id"], "n_a")
        return {"state": "n_a", "reason": "sans_agent"}
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None:
        erreur = f"ticket {slug}/{ticket_id} introuvable : la réponse est enregistrée, pas transmise"
        decisions.mark_delivery(row["id"], "failed", error=erreur, bump_attempt=True)
        return {"state": "failed", "reason": "ticket_missing", "error": erreur}
    envoi = messaging.send_to_ticket_agent(slug, ticket, _message(row))
    if envoi.get("ok"):
        decisions.mark_delivery(row["id"], "delivered", bump_attempt=True)
        return {"state": "delivered"}
    erreur = envoi.get("error") or ""
    decisions.mark_delivery(row["id"], "failed", error=erreur, bump_attempt=True)
    _log.warning("decision %s : livraison échouée (%s) — %s",
                 row["id"], envoi.get("reason") or "?", erreur)
    return {"state": "failed", "reason": envoi.get("reason") or "", "error": erreur}


@decisions_bp.get("/api/decisions")
def api_decisions_open():
    """Les cartes ouvertes, dans l'ordre du store (urgence puis ancienneté)."""
    return jsonify({"decisions": decisions.open_decisions(limit=200)})


@decisions_bp.get("/api/decisions/failed")
def api_decisions_failed():
    """Les réponses ENREGISTRÉES dont la livraison a échoué : sans cette liste, une réponse
    perdue en route resterait invisible (invariant I3)."""
    return jsonify({"decisions": decisions.failed_deliveries(limit=50)})


@decisions_bp.post("/api/decisions/<decision_id>/answer")
def api_decision_answer(decision_id: str):
    """enregistre ma reponse a une carte de decision (cle choisie ou texte libre)"""
    body = request.get_json(silent=True) or {}
    resultat = decisions.answer(decision_id,
                                answer_key=str(body.get("answer_key") or ""),
                                answer_text=str(body.get("answer_text") or ""))
    statut = resultat["status"]
    if statut != "ok":
        return _refus(statut, decision=resultat["decision"])
    return jsonify({"decision": resultat["decision"],
                    "delivery": _deliver(resultat["decision"])})


@decisions_bp.post("/api/decisions/<decision_id>/archive")
def api_decision_archive(decision_id: str):
    """sort de ma file une carte que je ne veux plus voir (agent mort, digest incomplet) sans la
    supprimer

    Une carte posée par un agent mort ne peut PAS être répondue — personne n'écoute — et elle
    reste pourtant dans la file. Vu le 2026-08-30 : une carte de 31 jours, incomplète, qui
    masquait les décisions du jour. On lui donne le `delivery='moot'` qui existait déjà pour la
    mort d'agent : elle sort de `open_decisions` en gardant sa question et sa trace.

    On refuse d'archiver une carte DÉJÀ répondue : ce serait masquer une réponse dont la
    livraison a peut-être échoué (invariant I3), et `answered_at` la sort déjà de la file.
    Ré-archiver, en revanche, est idempotent : un double-clic ne doit pas être une erreur.
    """
    row = decisions.get(decision_id)
    if row is None:
        return _refus("not_found")
    if row.get("answered_at"):
        return _refus("already_answered", decision=row)
    decisions.make_moot(decision_id, "archivée depuis le Bureau par l'utilisateur")
    return jsonify({"decision": decisions.get(decision_id)})


@decisions_bp.post("/api/decisions/<decision_id>/retry")
def api_decision_retry(decision_id: str):
    """Relance la livraison d'une réponse déjà donnée dont l'envoi avait échoué."""
    row = decisions.get(decision_id)
    if row is None:
        return _refus("not_found")
    if row["delivery"] != "failed":
        # Relancer une livraison réussie enverrait un DOUBLON à l'agent : on refuse en nommant
        # l'état réel plutôt que de laisser le front deviner pourquoi rien ne bouge.
        return erreur("not_failed", "la livraison de cette réponse n'a pas échoué", 409,
                      delivery=row["delivery"])
    return jsonify({"decision": decisions.get(decision_id), "delivery": _deliver(row)})
