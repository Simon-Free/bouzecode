"""Ranger une ligne qu'on ne lancera jamais.

Le 09/09 : « j'ai des erreurs quand j'essaie de marquer des tickets comme faits (cliquer sur
Faite pour archiver) » — POST /api/micros/<id>/etat renvoyait 409.

La cause n'était pas le front : le Bureau propose « Faite » sur toute ligne non archivée
(lignes.js, `gestes`), sans regarder `etat`. C'est le cycle de vie qui n'ouvrait `faite` que
depuis `lancee` : une ligne écrite puis jamais lancée n'avait AUCUNE sortie vers l'archive,
alors que « Écarter » (`abandonnee`) marchait déjà depuis le brouillon. Asymétrie, pas règle.

Archiver n'est pas lancer : marquer une ligne faite ne démarre rien, donc l'invariant « rien ne
part sans brief » (vérifié au lancement : titre + dépôt) n'a rien à protéger ici.
"""

import pytest

from bouzecode.web_v2.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _micro(client, titre, **body):
    response = client.post("/api/micros", json={"titre": titre, **body})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["micro"]


def _etat(client, micro_id, etat, **body):
    return client.post(f"/api/micros/{micro_id}/etat", json={"etat": etat, **body})


def test_je_peux_classer_faite_une_ligne_jamais_lancee(client):
    """Le clic « Faite » du Bureau sur un brouillon : il ARCHIVE, il ne renvoie pas 409."""
    micro = _micro(client, "ranger une idée que je ne lancerai pas")
    assert micro["etat"] == "brouillon"

    response = _etat(client, micro["id"], "faite")

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["micro"]["etat"] == "faite"


def test_je_peux_classer_faite_une_ligne_prete_mais_non_lancee(client):
    """Même geste depuis `prete` : marquer prête ne doit pas fermer la porte de l'archive."""
    micro = _micro(client, "ligne prête que je classe sans la lancer")
    assert _etat(client, micro["id"], "prete").status_code == 200

    response = _etat(client, micro["id"], "faite")

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["micro"]["etat"] == "faite"


def test_la_raison_du_classement_est_conservee(client):
    """Classer sans lancer garde le POURQUOI — c'est souvent là qu'est l'information."""
    micro = _micro(client, "doublon d'un ticket déjà traité")

    response = _etat(client, micro["id"], "faite", pourquoi="déjà fait par un autre ticket")

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["micro"]["pourquoi"] == "déjà fait par un autre ticket"


def test_une_ligne_archivee_reste_un_cul_de_sac(client):
    """Le fix ouvre une sortie, il n'ouvre pas tout : `faite` reste un état terminal."""
    micro = _micro(client, "ligne classée puis re-classée")
    assert _etat(client, micro["id"], "faite").status_code == 200

    assert _etat(client, micro["id"], "abandonnee").status_code == 409
