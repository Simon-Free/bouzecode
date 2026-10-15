# [desc] Branche le client HTTP de l'outil Agent (`multi_agent.client_tickets`) sur le client de test Flask : les tests passent par la VRAIE route de création, comme l'outil d'un manager. [/desc]
from __future__ import annotations

from bouzecode.backend.core.local_http import LocalServerError
from bouzecode.backend.multi_agent import client_tickets


def brancher(monkeypatch, client) -> None:
    """`client_tickets._appel` répond par `client` (application de test) au lieu d'un vrai HTTP."""
    def appel(methode: str, chemin: str, corps: dict | None = None, timeout: int = 60,
              en_tetes: dict | None = None) -> dict:
        reponse = client.open(chemin, method=methode, json=corps, headers=en_tetes or {})
        donnees = reponse.get_json(silent=True) or {}
        if reponse.status_code >= 400:
            raise LocalServerError(f"HTTP {reponse.status_code}", status=reponse.status_code,
                                   corps=donnees)
        return donnees
    monkeypatch.setattr(client_tickets, "_appel", appel)
