"""Ce que l'utilisateur LIT en haut de son Bureau : des compteurs qui veulent dire quelque chose.

Plainte du 2026-09-07, mot pour mot : « J'ai encore le "On m'attend / Rien ne t'attend. (1)
À faire (14)" ». Deux défauts derrière cette phrase :

1. « À faire » comptait TOUT ce qui était `a_faire`, arbitrages humains compris — or ceux-là
   étaient déjà affichés dans « À décider ». Une ligne comptée deux fois rend le total
   ininterprétable, et c'est ce qui a fait dire « je ne suis pas sûr que les 14 tâches soient
   encore pertinentes ».
2. Une file vide gardait son titre et sa phrase à l'écran.

Le comptage s'affiche en JS, donc non testable en pytest. C'est pourquoi `GET /api/board`
expose `counts.a_faire_travail` : la règle métier vit côté serveur, elle est prouvable ici, et
le front n'a plus à la re-dériver.
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
    """Une tâche telle qu'il en reste 15 en base : créée AVANT la garde G1 (donc via le service)."""
    defauts = {"title": "sans titre", "intent": "", "project_slug": "",
               "owner": "moi", "policy": "observer"}
    defauts.update(champs)
    return tasks.create_task(**defauts)


def _counts(client):
    response = client.get("/api/board")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["counts"]


def test_un_arbitrage_ne_gonfle_plus_la_file_de_travail(client):
    """Le cas exact des 9 lignes mesurées : un pourquoi, pas de dépôt, pas de ticket."""
    _heritee(title="nature de cabine SA=0/PC | SC=9",
             intent="à confirmer avec le métier avant tout calcul")
    #  `owner="moi"` (le défaut) : une tâche `owner=agent` en `a_faire` sans ticket est écartée du
    #  board vivant par `_board_live.is_live` — « un ticket que personne n'a lancé ne demande pas de
    #  décision aujourd'hui ». Les 15 lignes réellement en base sont d'ailleurs toutes `owner=moi`.
    #  Ce qui la range dans le TRAVAIL et non dans les arbitrages, c'est son dépôt renseigné.
    _heritee(title="refaire l'ingestion GEN*", intent="le correctif est livré, pas exécuté",
             project_slug="demo_ingestion")

    counts = _counts(client)
    assert counts["arbitrages"] == 1
    #  Deux tâches `a_faire`, mais UNE SEULE est du travail : l'arbitrage est ailleurs.
    assert counts["a_faire"] == 2
    assert counts["a_faire_travail"] == 1


def test_un_bureau_sans_arbitrage_compte_tout_comme_du_travail(client):
    """Pas de reclassement abusif : une tâche portée par un dépôt reste du travail."""
    _heritee(title="purger les conversations de test", intent="56 tickets à relire",
             project_slug="bouzecode")

    counts = _counts(client)
    assert counts["arbitrages"] == 0
    assert counts["a_faire_travail"] == counts["a_faire"] == 1


def test_migrer_un_arbitrage_le_retire_des_deux_compteurs(client):
    """Le geste de l'utilisateur : la ligne quitte l'écran des tâches pour devenir un brouillon."""
    tache = _heritee(title="trier les 10 reliquats ISO DEMODB",
                     intent="savoir lesquels sont encore utiles")
    assert _counts(client)["arbitrages"] == 1

    migration = client.post(f"/api/tasks/{tache['id']}/migrer", json={})
    assert migration.status_code == 201, migration.get_data(as_text=True)

    counts = _counts(client)
    assert counts["arbitrages"] == 0
    assert counts["a_faire_travail"] == 0
    #  Rien n'est perdu : le brief est devenu une micro-tâche en brouillon.
    micros = client.get("/api/micros?etat=brouillon").get_json()["micros"]
    assert [micro["titre"] for micro in micros] == ["trier les 10 reliquats ISO DEMODB"]
