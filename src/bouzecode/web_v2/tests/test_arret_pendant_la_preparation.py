"""« Arrêter » pendant que la tâche se prépare : aucun agent ne doit finir le travail.

Avant, l'arrêt posait l'échec de lancement sans prévenir le lancement de fond. Celui-ci créait
l'agent quand même, et `add_run` effaçait l'échec : l'agent travaillait jusqu'au bout et la
tâche passait « À vérifier » au lieu de « Arrêté par toi ». Vu en E2E sur
test_tache_en_echec_continuer : `lancer` puis `arreter` dans la même seconde.

Le lancement de fond est rejoué ici à la main (`sans_spawn` en capture les arguments), avec un
faux `create_agent` : aucun process ne démarre.
"""
from types import SimpleNamespace

import pytest

from bouzecode.web_v2.services.work import dispatch, micros, taches_actions
from bouzecode.web_v2.tests.test_v3_gestes_des_taches import (  # noqa: F401 — fixtures
    _ticket, client, depot, sans_spawn,
)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import ecrire_agent, ligne
from bouzecode.web_v2.runtime.runner import agent_creation

#  Le VRAI lancement de fond, pris avant que `sans_spawn` ne le remplace par un compteur.
LANCEMENT_DE_FOND = dispatch._launch_bg


@pytest.fixture()
def spawns(monkeypatch):
    crees: list[str] = []

    def faux_create_agent(*_args, **_kwargs):
        agent_id = f"5e5e5e5e5e{len(crees):02d}"
        crees.append(agent_id)
        ecrire_agent(agent_id, vivant=True, ipc="running")
        return SimpleNamespace(agent_id=agent_id)
    monkeypatch.setattr(agent_creation, "create_agent", faux_create_agent)
    return crees


@pytest.fixture()
def tues(monkeypatch):
    arretes: list[str] = []
    monkeypatch.setattr(taches_actions, "_tuer", lambda agent_id: arretes.append(agent_id) or "")
    return arretes


def _lancee(client, depot):
    micro = micros.create_micro(titre="t", projet_slug=depot)
    assert client.post(f"/api/micros/{micro['id']}/lancer").status_code == 200
    return micro


def test_arreter_avant_le_spawn_empeche_l_agent_de_demarrer(client, depot, sans_spawn, spawns):
    micro = _lancee(client, depot)
    assert client.post(f"/api/micros/{micro['id']}/arreter").status_code == 200

    LANCEMENT_DE_FOND(*sans_spawn[0])   # le lancement de fond arrive au bout de sa préparation

    assert spawns == [], "l'agent a démarré malgré l'arrêt"
    assert len(sans_spawn) == 1
    vue = ligne(client, micro["id"])
    assert (vue["statut_ui"], vue["motif"]) == ("en_echec", "arrete")


def test_arreter_pendant_le_spawn_arrete_l_agent_qui_vient_de_naitre(
        client, depot, sans_spawn, spawns, tues, monkeypatch):
    micro = _lancee(client, depot)
    create_agent = agent_creation.create_agent

    def spawn_puis_arret(*args, **kwargs):
        agent = create_agent(*args, **kwargs)
        #  L'arrêt arrive pendant le spawn : le process existe, son run n'est pas encore posé.
        assert client.post(f"/api/micros/{micro['id']}/arreter").status_code == 200
        return agent
    monkeypatch.setattr(agent_creation, "create_agent", spawn_puis_arret)

    LANCEMENT_DE_FOND(*sans_spawn[0])

    assert len(spawns) == 1 and tues == spawns, "l'agent né pendant l'arrêt n'a pas été arrêté"
    slug, ticket = _ticket(sans_spawn[0][1]["id"])
    assert [r["agent_id"] for r in ticket["runs"]] == spawns, "l'agent arrêté doit rester visible"


def test_arreter_juste_apres_le_run_arrete_l_agent(client, depot, sans_spawn, spawns, tues):
    micro = _lancee(client, depot)
    slug, ticket = _ticket(sans_spawn[0][1]["id"])
    LANCEMENT_DE_FOND(*sans_spawn[0])
    #  La préparation vue par l'écran (sans agent) est périmée : le run vient d'être posé.
    assert dispatch.arreter_la_preparation(slug, ticket) == spawns[0]
    vue = {"slug": slug, "ticket_id": ticket["id"], "agent_id": ""}
    assert taches_actions._arreter_passage(vue) == (spawns[0], None)
    assert tues == spawns
