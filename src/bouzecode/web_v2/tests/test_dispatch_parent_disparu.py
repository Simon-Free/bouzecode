# [desc] Un manager dont l'enregistrement a disparu sous lui est REFUSÉ en étant nommé, jamais par une erreur réseau. [/desc]
"""Quand le serveur ne connaît plus l'agent qui dispatche, il doit le DIRE.

L'incident du 2026-07-28 : pendant qu'un manager tournait, tout son dossier a été déplacé
dans `web_agents/_trash/`. Il n'héritait donc plus d'aucun projet, et ses dispatchs étaient
refusés — avec le message « ton agent n'est rattaché à aucun projet ouvert », qui envoie
chercher une erreur de configuration au lieu de sa propre disparition.

On dispatche par l'API RÉELLE (`POST /api/dispatch`). Ces cas s'arrêtent avant toute
création de ticket : aucun worktree, aucun process.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.routes.work import fleet as fleet_route


@pytest.fixture()
def client(monkeypatch):
    from bouzecode.web_v2.app import create_app

    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    # Le rebornage du warm-pool viserait le parc d'agents RÉEL : neutralisé.
    monkeypatch.setattr(fleet_route.fleet, "sweep_warm_pool", lambda: None)
    return create_app().test_client()


def test_un_parent_que_le_serveur_ne_connait_plus_est_nomme(client):
    """Enregistrement d'agent disparu → refus explicite, et surtout PAS une erreur réseau."""
    reponse = client.post("/api/dispatch",
                          json={"prompt": "construis X", "parent": "0123456789ab"})

    # Le serveur RÉPOND, normalement : un parent inconnu n'a jamais produit d'erreur HTTP.
    # C'est ce qui disqualifie « l'agent purgé » comme explication du 407 de production.
    assert reponse.status_code == 200
    assert reponse.get_json()["needs_project"] is True
    assert reponse.get_json()["parent_unknown"] is True


def test_un_lancement_manuel_n_est_pas_une_disparition(client):
    """Sans projet et sans parent managé, on manque un projet — on n'a rien « perdu »."""
    reponse = client.post("/api/dispatch", json={"prompt": "construis X"})

    assert reponse.status_code == 200
    assert reponse.get_json()["needs_project"] is True
    assert reponse.get_json()["parent_unknown"] is False
