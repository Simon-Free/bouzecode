"""Lot B — j'écris et j'annote DIRECTEMENT sur la ligne, sans détour par un brouillon.

Ce que ces tests prouvent, du point de vue de l'utilisateur :
  1. une ligne qui a un titre et un dépôt est lançable TOUT DE SUITE — aucun geste
     « Marquer PRÊTE » à franchir avant ;
  2. une ligne DÉJÀ LANCÉE reste modifiable : un lancement raté enrichit le brief au
     lieu de le perdre ;
  3. une note s'ajoute sur n'importe quelle ligne, quel que soit son état ;
  4. ce qui est refusé, c'est un ordre inexécutable (sans dépôt) — et le refus parle du
     BRIEF, plus jamais d'un état à conquérir.

Aucun agent n'est démarré ici : le seul lancement tenté est celui qui échoue AVANT le
dispatch, faute de dépôt.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _ligne(client, titre: str, **champs) -> dict:
    reponse = client.post("/api/micros", json={"titre": titre, **champs})
    assert reponse.status_code == 201, reponse.get_data(as_text=True)
    return reponse.get_json()["micro"]


def _lu(client, micro_id: str) -> dict:
    reponse = client.get(f"/api/micros/{micro_id}")
    assert reponse.status_code == 200, reponse.get_data(as_text=True)
    return reponse.get_json()["micro"]


def test_une_ligne_avec_son_depot_est_lancable_sans_geste_prealable(client):
    """Le détour « migrer en brouillon puis marquer prête » n'existe plus."""
    ligne = _ligne(client, "porter le décodeur TRAF", projet_slug="demo_ingestion")
    assert ligne["etat"] == "brouillon"
    assert ligne["lancable"] is True, "une ligne briefée doit partir sans clic rituel"


def test_une_ligne_sans_depot_n_est_pas_lancable_mais_reste_editable(client):
    """Ce qui manque est nommé (le dépôt), et ça n'empêche pas d'écrire."""
    ligne = _ligne(client, "une idée à creuser")
    assert ligne["lancable"] is False

    patch = client.patch(f"/api/micros/{ligne['id']}",
                         json={"corps": "contexte : la maille ID_TRAIN est fausse"})
    assert patch.status_code == 200, patch.get_data(as_text=True)
    assert "ID_TRAIN" in _lu(client, ligne["id"])["corps"]


def test_j_edite_et_j_annote_une_ligne_deja_lancee(client):
    """Un lancement raté ne fige rien : le brief se corrige sur place."""
    ligne = _ligne(client, "réparer le parseur", projet_slug="demo_ingestion")
    #  Passage direct brouillon -> lancee : c'est justement ce que le lot B autorise.
    bascule = client.post(f"/api/micros/{ligne['id']}/etat", json={"etat": "lancee"})
    assert bascule.status_code == 200, bascule.get_data(as_text=True)
    assert _lu(client, ligne["id"])["etat"] == "lancee"

    patch = client.patch(f"/api/micros/{ligne['id']}",
                         json={"titre": "réparer le parseur (format 3)",
                               "corps": "piège réel : la date est en BCD"})
    assert patch.status_code == 200, patch.get_data(as_text=True)
    relu = _lu(client, ligne["id"])
    assert relu["titre"] == "réparer le parseur (format 3)"
    assert "BCD" in relu["corps"]

    note = client.post(f"/api/micros/{ligne['id']}/precisions",
                       json={"texte": "l'essai précédent a échoué sur l'entête", "auteur": "humain"})
    assert note.status_code == 201, note.get_data(as_text=True)
    assert "entête" in _lu(client, ligne["id"])["prompt"]


def test_lancer_sans_depot_est_refuse_pour_le_brief_pas_pour_l_etat(client):
    """Le refus doit parler de ce qui manque, jamais d'un état à conquérir."""
    ligne = _ligne(client, "faire quelque chose, un jour")
    refus = client.post(f"/api/micros/{ligne['id']}/lancer", json={})
    assert refus.status_code == 400, refus.get_data(as_text=True)
    #  `get_data` rend le JSON échappé en \uXXXX : on lit le message DÉCODÉ, sinon
    #  aucun assert sur un mot accentué ne peut matcher.
    message = refus.get_json()["error"]["message"]
    assert "dépôt" in message
    assert "prete" not in message and "prête" not in message, \
        "plus aucun péage d'état dans le message de refus"
