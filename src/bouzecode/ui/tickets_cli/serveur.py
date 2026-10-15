# [desc] Coexistence de la CLI tickets avec le serveur web_v2 : détecte le serveur de référence (verrou du parc), lui délègue les écritures en HTTP (jeton local, sans proxy), normalise les erreurs. [/desc]
"""Règle de coexistence (une seule, vérifiable) :

* **serveur de référence vivant** (il tient le verrou `<parc>/.serveur_de_reference.lock`,
  cf. `web_v2/reference.py`) → toute commande d'ÉCRITURE passe par son API HTTP
  (`backend/core/local_http.py`, jeton local joint) ; `suivre` se contente de LIRE le store :
  c'est son watchdog qui constate les fins et suit Rundeck ;
* **pas de serveur** → la CLI agit EN PROCESS (mêmes services que les routes) et `suivre`
  tient le verrou de référence le temps de chacun de ses pas (`reference.pour_un_pas_cli`) :
  jamais deux suivis de la même flotte en même temps.

Les lectures (`lister`, `voir`, `projets`) lisent toujours le store en process : elles
n'écrivent rien, elles n'ont pas à passer par le serveur.
"""
from __future__ import annotations

import os

PORT_PAR_DEFAUT = 5056


class ErreurGeste(Exception):
    """Un geste refusé, à la forme de l'API : code machine, message français, détails."""

    def __init__(self, code: str, message: str, status: int = 409, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details or {}

    def corps(self) -> dict:
        erreur = {"code": self.code, "message": self.message}
        if self.details:
            erreur["details"] = self.details
        return {"error": erreur, "status": self.status}


def vivant() -> bool:
    from bouzecode.web_v2 import reference
    return reference.serveur_vivant()


def url_de_base() -> str:
    """L'URL du serveur de référence : son port déclaré dans la fiche du parc, sinon l'env."""
    from bouzecode.web_v2 import reference
    port = reference.detenteur().get("port")
    if port:
        return f"http://127.0.0.1:{int(port)}"
    defaut = f"http://127.0.0.1:{PORT_PAR_DEFAUT}"
    return (os.environ.get("BOUZECODE_WEB_BASE_URL") or defaut).rstrip("/")


def appeler(methode: str, route: str, corps: dict | None = None) -> dict:
    """Appel à l'API du serveur ; lève `ErreurGeste` avec le code de l'API (ou `serveur_injoignable`)."""
    from bouzecode.backend.core.local_http import LocalServerError, local_json
    try:
        return local_json(methode, url_de_base() + route, corps, timeout=180)
    except LocalServerError as exc:
        erreur = exc.corps.get("error") if isinstance(exc.corps.get("error"), dict) else {}
        if erreur:
            raise ErreurGeste(str(erreur.get("code") or "erreur"), str(erreur.get("message")),
                              exc.status, erreur.get("details")) from exc
        code = "serveur_injoignable" if not exc.status else "erreur_serveur"
        raise ErreurGeste(code, str(exc), exc.status or 503) from exc


def en_process(fonction, *args, **kwargs):
    """Appelle un service en process ; ses refus deviennent `ErreurGeste` (même code que l'API)."""
    from bouzecode.web_v2.services.erreurs import Refus
    from bouzecode.web_v2.services.work import ticket_fsm
    from bouzecode.web_v2.services.work._ligne_ticket import VersionObsolete
    try:
        return fonction(*args, **kwargs)
    except Refus as refus:
        raise ErreurGeste(refus.code, refus.message, refus.status, refus.details) from refus
    except ticket_fsm.TransitionRefusee as exc:
        raise ErreurGeste(exc.code, str(exc), 409, exc.details) from exc
    except VersionObsolete as exc:
        raise ErreurGeste("version_obsolete", str(exc), 409, exc.details) from exc
