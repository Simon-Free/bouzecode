"""Ce que l'utilisateur LIT dans « Ça tourne » : uniquement ce qui tourne VRAIMENT.

Plainte du 2026-09-07, mot pour mot : « j'ai toujours les champs "Ca tourne" et "A faire"
(ça tourne a un ticket alors que rien ne tourne) ». Mesuré à l'écran : la seule tâche annoncée
« ça tourne » était une fixture dont le DERNIER évènement avait 11 jours. Aucun agent ne
tournait ; le board ne regardait nulle part la fraîcheur de l'activité.

La règle vit dans `build_board` et se lit dans le payload : `age_s` (secondes depuis le dernier
évènement) et `stale` (vrai pour une tâche `en_cours` sans nouvelle depuis plus de 30 min).
Le front n'a donc aucune règle métier à re-dériver — et `counts` dit la vérité : une tâche figée
quitte `en_cours` pour `figees`, au lieu de gonfler un compteur qu'on n'ouvre plus.
"""
from datetime import datetime, timedelta

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import tasks
from bouzecode.web_v2.services.work.board import _age_seconds

#  Les tâches fabriquées par ces tests sont CLÔTURÉES en teardown. Sans ça, chaque exécution
#  laisserait une ligne de plus sur le board réel de l'utilisateur : c'est exactement ce qui a
#  produit les 4 doublons « preuve du lien Teams entrant » qu'il dénonce dans « À faire ».
_CREEES: list[str] = []


@pytest.fixture(autouse=True)
def _sans_residu():
    yield
    while _CREEES:
        tasks.close_task(_CREEES.pop(), outcome="abandonnee")


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _board(client):
    response = client.get("/api/board")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _ligne(board, task_id):
    return next((tache for tache in board["tasks"] if tache["id"] == task_id), None)


def _creer(titre, intent="preuve de fraicheur"):
    task_id = tasks.create_task(title=titre, intent=intent, project_slug="",
                                owner="moi", policy="observer")["id"]
    _CREEES.append(task_id)
    return task_id


def _en_cours_depuis(titre, secondes):
    """Une tâche que le board voit `en_cours`, dont le dernier évènement a `secondes` d'âge.

    `owner='moi'` : l'état est SAISI, pas dérivé de tickets — c'est ce qui permet de monter le
    cas sans fabriquer un ticket en base, et la règle de fraîcheur ne regarde que l'évènement.
    """
    task_id = _creer(titre)
    tasks.update_task(task_id, state="en_cours")
    at = (datetime.now() - timedelta(seconds=secondes)).isoformat(timespec="seconds")
    tasks.add_event(task_id, actor="agent", kind="note", label="dernier signe de vie", at=at)
    return task_id


def test_une_tache_sans_nouvelle_depuis_onze_jours_ne_tourne_plus(client):
    avant = _board(client)["counts"]
    task_id = _en_cours_depuis("figee depuis onze jours", 11 * 86_400)

    board = _board(client)
    ligne = _ligne(board, task_id)
    assert ligne is not None, "la tâche figée doit RESTER visible : on ne la supprime pas en silence"
    assert ligne["stale"] is True
    assert ligne["age_s"] >= 11 * 86_400 - 60
    #  Le mensonge disparaît du compteur : « ça tourne » ne compte plus cette tâche…
    assert board["counts"]["en_cours"] == avant["en_cours"]
    #  … et elle est comptée là où l'utilisateur peut agir (relancer ou clore).
    assert board["counts"]["figees"] == avant.get("figees", 0) + 1


def test_une_tache_active_depuis_une_minute_tourne_bien(client):
    avant = _board(client)["counts"]
    task_id = _en_cours_depuis("active a l'instant", 60)

    board = _board(client)
    ligne = _ligne(board, task_id)
    assert ligne is not None
    assert ligne["stale"] is False
    assert ligne["age_s"] < 600
    assert board["counts"]["en_cours"] == avant["en_cours"] + 1
    assert board["counts"]["figees"] == avant.get("figees", 0)


def test_une_tache_qui_vient_de_naitre_ne_part_pas_en_fige(client):
    """Créer une tâche ne doit pas la faire tomber immédiatement dans « Figé »."""
    task_id = _creer("tout juste creee", intent="preuve")
    tasks.update_task(task_id, state="en_cours")

    ligne = _ligne(_board(client), task_id)
    assert ligne is not None
    assert ligne["stale"] is False
    assert ligne["age_s"] is None or ligne["age_s"] < 600


def test_sans_historique_lage_est_inconnu_pas_zero():
    """Une tâche sans évènement lisible a un âge INCONNU : `None`, jamais 0.

    Zéro voudrait dire « active à l'instant » — le mensonge inverse. La règle est testée sur le
    helper pur parce qu'une tâche créée par le service porte toujours un évènement daté.
    """
    assert _age_seconds({}) is None
    assert _age_seconds({"at": ""}) is None
    assert _age_seconds({"at": "pas une date"}) is None
    assert _age_seconds({"at": datetime.now().isoformat(timespec="seconds")}) < 5
