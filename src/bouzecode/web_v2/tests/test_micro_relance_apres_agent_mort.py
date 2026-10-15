"""Relancer une ligne du Bureau dont l'agent est MORT.

Signalé le 09/09 : « je n'arrive pas à relancer l'agent ». Le bouton « Lancer un agent »
répondait 409 « cette ligne est déjà lancée : renvoie-la en brouillon pour la relancer »
alors que l'agent du ticket était terminé depuis deux heures — et le geste promis par le
refus (retour en brouillon) n'existait dans AUCUN bouton de cet état. Cul-de-sac.

Le refus ne protège qu'une chose : le CLONAGE d'un travail en cours (double-clic, ou
l'assistant qui rejoue son ordre). Il doit donc tomber quand un ticket relié tourne
ENCORE, et seulement là.
"""
import json

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import _persistence, constats, dispatch, projects, tickets
from bouzecode.web_v2.services.work.fsm import etats

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
    """Compte les VRAIS départs d'agent sans en démarrer aucun."""
    appels: list[tuple] = []

    def faux_launch_bg(*args, **kwargs):
        appels.append(args)

    monkeypatch.setattr(dispatch, "_launch_bg", faux_launch_bg)
    return appels


def _micro(client, titre, **body):
    response = client.post("/api/micros", json={"titre": titre, **body})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["micro"]


def _eteindre(ticket_id: str) -> None:
    """L'agent a tourné puis fini son tour : le ticket a quitté les états actifs.

    Le faux spawn de ce test ne rattache aucun run : on rejoue ce que le vrai chemin aurait
    fait (rattachement du run, puis fin du run constatée par le hook)."""
    for slug, ticket in _persistence.all_tickets():
        if str(ticket.get("id") or "") == ticket_id:
            tickets.add_run(slug, ticket, "agent-mort", "work", "m")
            constats.fin_de_run(slug, ticket_id, "agent-mort", "final_answer", final_answer=True)
            assert tickets.get_ticket(slug, ticket_id)["state"] == etats.DELIVERED
            return
    raise AssertionError(f"ticket {ticket_id} introuvable en base")


def test_relancer_est_refuse_tant_que_le_ticket_tourne(app, depot_ouvert, sans_spawn):
    """Non-régression de l'anti-doublon : deux clics d'affilée ne lancent qu'un agent."""
    client = app.test_client()
    micro = _micro(client, "ne pas cloner un travail en cours")

    premier = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})
    assert premier.status_code == 200, premier.get_data(as_text=True)

    second = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})
    assert second.status_code == 409, second.get_data(as_text=True)
    assert len(sans_spawn) == 1, "un second clic a lancé un second agent"


def test_relancer_une_ligne_dont_l_agent_est_mort_repart(app, depot_ouvert, sans_spawn):
    """Le geste que l'utilisateur ne pouvait plus faire : relancer ce qui ne tourne plus."""
    client = app.test_client()
    micro = _micro(client, "relancer apres la mort de l'agent")

    premier = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})
    assert premier.status_code == 200, premier.get_data(as_text=True)
    ticket_id = premier.get_json()["ticket_id"]
    assert ticket_id

    _eteindre(ticket_id)

    relance = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})
    assert relance.status_code == 200, relance.get_data(as_text=True)
    assert relance.get_json()["ticket_id"], "la relance n'a produit aucun ticket"
    assert len(sans_spawn) == 2, "la relance n'a lancé aucun agent"


def test_une_ligne_archivee_reste_refusee(app, depot_ouvert, sans_spawn):
    """Une ligne classée n'a rien à relancer : le 409 y reste, et l'UI offre « Rouvrir »."""
    client = app.test_client()
    micro = _micro(client, "ligne classee faite")
    etat = client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "abandonnee"})
    assert etat.status_code == 200, etat.get_data(as_text=True)

    refus = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})
    assert refus.status_code == 409, refus.get_data(as_text=True)
    assert not sans_spawn
