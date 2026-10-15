"""Deux clics sur « Lancer un agent » ne lancent QU'UN agent — pas deux.

Symptôme utilisateur (2026-09-08) : une micro-tâche du Bureau part EN DOUBLE — deux agents,
deux tickets, sur le même brief. Le bouton « Lancer un agent » (`lignes.js`) n'est pas désarmé
pendant l'appel, et la route `/api/micros/<id>/lancer` ne vérifie RIEN : elle dispatche, PUIS
lie le ticket, PUIS marque l'état. Deux requêtes concurrentes lisent donc toutes deux la ligne
AVANT tout marquage et dispatchent chacune leur agent.

Le test reproduit exactement cette course : la fenêtre est élargie à l'endroit précis où elle
existe en production — après toutes les gardes de la route, juste avant `dispatch()` — en
ralentissant `prompt_de`. Deux clients de la MÊME application postent en parallèle.

Preuve attendue : `_launch_bg` (le vrai départ d'un agent) n'est appelé QU'UNE fois, et le
second appel repart en 409 explicite au lieu de cloner le travail.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import dispatch, projects
from bouzecode.web_v2.services.work import micros as micros_service

SLUG = "demo-application"


@pytest.fixture()
def app():
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def depot_ouvert(tmp_path):
    """Un dépôt ENREGISTRÉ (dossier non-git → isolation `shared`, aucun worktree créé)."""
    path = tmp_path / "demo_application"
    path.mkdir()
    entries = [{"slug": SLUG, "name": "demo_application", "path": str(path)}]
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(entries), encoding="utf-8")
    return entries[0]


@pytest.fixture()
def sans_spawn(monkeypatch):
    """Compte les VRAIS départs d'agent sans en démarrer aucun.

    `dispatch()` part en `defer=True` : c'est `_launch_bg` (worktree + spawn d'un process)
    qu'il faut neutraliser. La longueur de cette liste EST le nombre d'agents lancés."""
    appels: list[tuple] = []

    def faux_launch_bg(*args, **kwargs):
        appels.append(args)

    monkeypatch.setattr(dispatch, "_launch_bg", faux_launch_bg)
    return appels


def _micro(client, titre, **body):
    response = client.post("/api/micros", json={"titre": titre, **body})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["micro"]


def test_deux_lancements_concurrents_ne_lancent_qu_un_agent(
        app, depot_ouvert, sans_spawn, monkeypatch):
    client = app.test_client()
    micro = _micro(client, "corriger le double lancement du Bureau")

    #  La fenêtre de course, là où elle est en production : entre la lecture de la ligne
    #  et le dispatch. On la rend franche pour que le test soit déterministe.
    rendez_vous = threading.Barrier(2, timeout=10)
    prompt_reel = micros_service.prompt_de

    def prompt_lent(micro_dict):
        try:
            rendez_vous.wait()
        except threading.BrokenBarrierError:
            pass
        time.sleep(0.2)
        return prompt_reel(micro_dict)

    monkeypatch.setattr(micros_service, "prompt_de", prompt_lent)

    statuts: list[int] = []
    verrou = threading.Lock()

    def cliquer():
        reponse = app.test_client().post(f"/api/micros/{micro['id']}/lancer",
                                         json={"projet_slug": SLUG})
        with verrou:
            statuts.append(reponse.status_code)

    fils = [threading.Thread(target=cliquer) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)

    assert len(sans_spawn) == 1, (
        f"la même ligne a lancé {len(sans_spawn)} agents : le travail part en double")
    assert sorted(statuts) == [200, 409], (
        f"attendu un lancement accepté et un refus explicite, reçu {sorted(statuts)}")


def test_relancer_une_ligne_deja_lancee_est_refuse_sans_cloner(
        app, depot_ouvert, sans_spawn):
    """Le cas simple, sans concurrence : re-cliquer ne relance pas, et le dit."""
    client = app.test_client()
    micro = _micro(client, "ne pas relancer deux fois la même ligne")

    premier = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})
    assert premier.status_code == 200, premier.get_data(as_text=True)
    assert premier.get_json()["ticket_id"]

    second = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})
    assert second.status_code == 409, second.get_data(as_text=True)
    assert "déjà" in second.get_json()["error"]["message"]
    assert len(sans_spawn) == 1, "un second clic a lancé un second agent"
