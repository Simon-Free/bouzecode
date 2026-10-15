# [desc] Forme UNIQUE des erreurs de l'API : {"error": {"code", "message", "details"?}} + code HTTP >= 400 (spec ticketing §9). [/desc]
"""Une seule forme d'erreur pour toute l'API (spec ticketing B6, §9 « Erreurs ») :

    {"error": {"code": "snake_case", "message": "phrase en français", "details": {...}}}

avec un code HTTP >= 400. `code` sert à la logique du client, `message` à l'affichage ;
`details` (facultatif) porte les données utiles (état courant d'un 409, suggestions…).
Le front (`static/js/lib/ui.js`) lit `error.code` et `error.message`.
"""
from __future__ import annotations

import logging
import re

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

_log = logging.getLogger(__name__)


def corps_d_erreur(code: str, message: str, **details) -> dict:
    erreur = {"code": code, "message": message}
    if details:
        erreur["details"] = details
    return {"error": erreur}


def erreur(code: str, message: str, status: int, **details):
    """La réponse Flask d'une erreur : (corps JSON, code HTTP)."""
    if status < 400:
        raise ValueError(f"une erreur se rend avec un code HTTP >= 400, pas {status}")
    return jsonify(corps_d_erreur(code, message, **details)), status


def _code_http(exc: HTTPException) -> str:
    """« Not Found » → `not_found` : un code machine stable pour les erreurs du protocole."""
    return re.sub(r"[^a-z0-9]+", "_", (exc.name or "erreur").lower()).strip("_")


def installer(app) -> None:
    """Toute erreur d'une route /api/ sort à la forme unique : les refus métier des services
    (`services.erreurs.Refus`), ceux de la machine à états (409, l'état courant du ticket dans
    `details`), les erreurs du protocole HTTP (404 route inconnue, 405…) et les 500 (journalisées
    avec leur pile). Les pages HTML gardent les pages d'erreur de Flask."""
    from ..services.erreurs import Refus
    from ..services.work import ticket_fsm
    from ..services.work.fsm.stockage import RunDejaRattache

    @app.errorhandler(HTTPException)
    def _protocole(exc: HTTPException):
        if not request.path.startswith("/api/") or (exc.code or 500) < 400:
            return exc
        return erreur(_code_http(exc), exc.description or exc.name, exc.code or 500)

    @app.errorhandler(500)
    def _interne(exc):
        _log.error("erreur interne sur %s %s", request.method, request.path,
                   exc_info=getattr(exc, "original_exception", None) or exc)
        if not request.path.startswith("/api/"):
            return "Erreur interne du serveur", 500
        return erreur("erreur_interne", "erreur interne du serveur (journalisée)", 500)

    @app.errorhandler(Refus)
    def _refus(exc: Refus):
        return erreur(exc.code, exc.message, exc.status, **exc.details)

    @app.errorhandler(ticket_fsm.TransitionRefusee)
    def _transition_refusee(exc: ticket_fsm.TransitionRefusee):
        return erreur(exc.code, str(exc), 409, **exc.details)

    @app.errorhandler(ticket_fsm.VersionObsolete)
    def _version_obsolete(exc: ticket_fsm.VersionObsolete):
        return erreur("version_obsolete", str(exc), 409, **exc.details)

    @app.errorhandler(RunDejaRattache)
    def _run_deja_rattache(exc: RunDejaRattache):
        return erreur("run_deja_rattache", str(exc), 409)
