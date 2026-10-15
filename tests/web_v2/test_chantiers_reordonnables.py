# [desc] ool_calls>
# <tool_use name="Methodology" id="m1"><param name="content"><![CDATA[## Tour 20 — demande hors-chantier : description one-line du f [/desc]
"""Les chantiers se rangeaient par `created_at`, sans aucun moyen de les reordonner.

Le drag/drop existait pour les TACHES (poignee dans lignes.js -> PATCH /api/micros/<id> {macro_id}),
mais pas pour les CHANTIERS : l'ordre d'affichage venait de `list_macros()` (ORDER BY created_at) et
rien ne pouvait le changer. Ce test prouve le contrat cote HTTP, la ou l'ecran tape reellement :
on cree trois chantiers, on demande un nouvel ordre, et GET /api/lignes doit le rendre — et le
rendre ENCORE apres un nouveau client (donc persiste en base, pas garde en memoire de process).

Regle verrouillee : le test ne regarde QUE les trois chantiers qu'il a crees, pour rester vrai
meme si la base contient d'autres chantiers.
"""

import pytest

from bouzecode.web_v2.services.work import _persistence


def _client(tmp_path, monkeypatch):
    """Un vrai client Flask sur une vraie base SQLite jetable.

    `_persistence.TICKETS_DIR` est la SOURCE que `_db_path()` re-derive a chaque transaction :
    la deplacer suffit a isoler le test, sans un seul mock.
    """
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _cree_chantier(client, titre):
    reponse = client.post("/api/macros", json={"titre": titre})
    assert reponse.status_code in (200, 201), (titre, reponse.status_code, reponse.data)
    charge = reponse.get_json()
    macro = charge.get("macro") or charge
    return macro["id"]


def _ordre_des_chantiers(client, ids):
    """L'ordre d'affichage tel que l'ecran le recoit, restreint aux chantiers du test."""
    reponse = client.get("/api/lignes")
    assert reponse.status_code == 200, reponse.data
    chantiers = reponse.get_json()["chantiers"]
    vus = [str(chantier["macro_id"]) for chantier in chantiers]
    return [identifiant for identifiant in vus if identifiant in set(ids)]


def test_chantiers_reordonnables_via_api(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    a = _cree_chantier(client, "Chantier A")
    b = _cree_chantier(client, "Chantier B")
    c = _cree_chantier(client, "Chantier C")

    #  Par defaut : l'ordre de creation.
    assert _ordre_des_chantiers(client, [a, b, c]) == [a, b, c]

    #  Le geste de l'utilisateur : il tire C tout en haut.
    reponse = client.post("/api/macros/reorder", json={"ordre": [c, a, b]})
    assert reponse.status_code == 200, (reponse.status_code, reponse.data)

    assert _ordre_des_chantiers(client, [a, b, c]) == [c, a, b]


def test_ordre_des_chantiers_survit_au_rechargement(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    a = _cree_chantier(client, "Chantier A")
    b = _cree_chantier(client, "Chantier B")
    c = _cree_chantier(client, "Chantier C")

    client.post("/api/macros/reorder", json={"ordre": [b, c, a]})

    #  Un client tout neuf = un rechargement de page : l'ordre doit venir de la base.
    autre = _client(tmp_path, monkeypatch)
    assert _ordre_des_chantiers(autre, [a, b, c]) == [b, c, a]


def test_reorder_refuse_un_ordre_vide(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reponse = client.post("/api/macros/reorder", json={"ordre": []})
    assert reponse.status_code == 400, (reponse.status_code, reponse.data)
