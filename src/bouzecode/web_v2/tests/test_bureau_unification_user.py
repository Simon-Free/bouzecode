"""Le Bureau UNIFIÉ, vu de l'écran : une seule liste de travail, les arbitrages à part.

Contexte mesuré le 2026-09-07 sur la base réelle : les 15 tâches affichées sous « À faire »
n'étaient PAS du travail. Six étaient du déchet de mise au point (une fixture `myproject`,
un `temp_verif_capture`, quatre doublons stricts « preuve du lien Teams entrant ») et neuf
étaient des ARBITRAGES humains sans dépôt (nature de cabine à confirmer, OTP Confluence,
droit IT de créer un bot Teams…). D'où la question de l'utilisateur : « je ne suis pas sûr
que les 14 tâches soient encore pertinentes ».

Ce que ce fichier verrouille, du point de vue de l'utilisateur :

- une tâche sans dépôt ni ticket, avec un pourquoi, est un arbitrage : elle ne pollue plus
  la file de travail ;
- une tâche héritée peut être MIGRÉE en brouillon d'un clic, sans perdre son pourquoi ;
- rien ne disparaît sans geste explicite : la migration close la ligne v1, elle ne
  supprime aucune donnée.

Tout passe par les VRAIES routes HTTP et la vraie base SQLite (isolée par la fixture
autouse `_isolate_production_state` du conftest).
"""
import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import tasks


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _heritee(**champs):
    """Une tâche telle qu'il en reste 15 en base : créée AVANT la garde G1.

    On passe par le service et non par `POST /api/tasks`, parce que la route refuse
    désormais une tâche sans porteur (c'est tout l'objet de G1). Ces lignes existent, il
    faut donc pouvoir les traiter — pas les recréer.
    """
    #  Les défauts vivent dans un dict fusionné, pas en kwargs explicites : sinon un test qui
    #  précise `title=` en fournirait DEUX valeurs (TypeError).
    defauts = {"title": "sans titre", "intent": "", "project_slug": "",
               "owner": "moi", "policy": "observer"}
    return tasks.create_task(**{**defauts, **champs})


def _board(client):
    response = client.get("/api/board")
    assert response.status_code == 200, response.get_data(as_text=True)
    return {tache["id"]: tache for tache in response.get_json()["tasks"]}


def _micros(client, **filtres):
    query = "&".join(f"{cle}={valeur}" for cle, valeur in filtres.items())
    response = client.get(f"/api/micros?{query}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["micros"]


# --------------------------------------------- D1 : « À faire » ne contient que du travail


def test_une_ligne_sans_depot_et_sans_ticket_est_un_arbitrage_pas_du_travail(client):
    """Le cas des 9 lignes réelles : un pourquoi long, aucun dépôt, personne à dispatcher."""
    arbitrage = _heritee(title="nature de la cabine SA=0/PC | SC=9",
                         intent="à confirmer avec le métier avant de coder quoi que ce soit")

    vue = _board(client)[arbitrage["id"]]
    assert vue["arbitrage"] is True, (
        "une tâche sans dépôt ni ticket n'est pas dispatchable : elle attend une décision")


def test_une_ligne_portee_par_un_depot_reste_du_travail(client):
    portee = _heritee(title="déplacer le profil default",
                      intent="backend/profiles/builtin", project_slug="bouzecode")

    assert _board(client)[portee["id"]]["arbitrage"] is False


# ------------------------------------------------- D2 : migrer, sans rien perdre ni supprimer


def test_je_migre_une_ligne_heritee_en_brouillon_et_son_pourquoi_survit(client):
    heritee = _heritee(title="purger les conversations de test",
                       intent="34 conversations de test sur 56 tickets « à relire »")

    migration = client.post(f"/api/tasks/{heritee['id']}/migrer", json={})
    assert migration.status_code == 201, migration.get_data(as_text=True)
    micro = migration.get_json()["micro"]

    #  Le titre reste une ligne, le pourquoi devient le corps : c'est le brief de l'agent.
    assert micro["titre"] == "purger les conversations de test"
    assert "34 conversations de test" in micro["corps"]
    #  Elle naît BROUILLON : migrer n'est pas lancer.
    assert micro["etat"] == "brouillon"

    brouillons = [m["id"] for m in _micros(client, etat="brouillon")]
    assert micro["id"] in brouillons


def test_la_ligne_migree_quitte_la_file_de_travail_sans_etre_supprimee(client):
    heritee = _heritee(title="trier les 10 reliquats ISO DEMODB", intent="ticket 39bc3dc0")
    client.post(f"/api/tasks/{heritee['id']}/migrer", json={})

    #  Elle n'encombre plus l'écran…
    assert heritee["id"] not in _board(client)
    #  …mais la donnée est toujours là, close avec sa raison : rien n'a été détruit.
    close = client.get("/api/tasks?closed=1").get_json()["tasks"]
    trace = [t for t in close if t["id"] == heritee["id"]]
    assert trace, "la ligne migrée doit rester consultable, pas disparaître de la base"
    assert trace[0]["outcome"] == "migre"


def test_migrer_deux_fois_ne_fabrique_pas_deux_brouillons(client):
    heritee = _heritee(title="volet B des cours de RM", intent="aucun chiffre communiqué")
    assert client.post(f"/api/tasks/{heritee['id']}/migrer", json={}).status_code == 201

    encore = client.post(f"/api/tasks/{heritee['id']}/migrer", json={})
    assert encore.status_code == 409, encore.get_data(as_text=True)
    assert len(_micros(client, etat="brouillon")) == 1


def test_migrer_une_ligne_inconnue_le_dit_clairement(client):
    refus = client.post("/api/tasks/nexistepas/migrer", json={})
    assert refus.status_code == 404


# ---------------------------------------------------------- D3 : les gestes existent à l'écran
