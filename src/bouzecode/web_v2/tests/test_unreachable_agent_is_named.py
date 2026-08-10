# [desc] Un ticket ouvert dont l'agent est INTROUVABLE le dit, et un envoi vers lui échoue franchement. [/desc]
"""Cas vécu du 28/07 : la fiche d'un agent VIVANT est partie à la corbeille. Le ticket
existait toujours, mais `runner.load_agent` renvoyait None — l'agent était injoignable.
Rien ne le signalait : le ticket se lisait comme un banal « planté », et l'envoi d'un
message se terminait sur « l'agent n'a pas pu être interrompu, réessaie » après deux
minutes d'interruptions inutiles. Quatre heures pour comprendre.

Ce qu'on prouve, du point de vue de qui regarde le board et tape un message :
  * le ticket ouvert NOMME l'anomalie au lieu de la ranger sous « planté » ;
  * un envoi vers cet agent échoue explicitement, en disant que RIEN n'est parti ;
  * l'échec porte un motif MACHINE, pour que le client ne le rejoue pas en boucle ;
  * aucun commentaire n'est journalisé : un message non parti ne laisse pas de trace
    qui ferait croire qu'il l'est.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.routes.work import tickets as troute
from bouzecode.web_v2.services.work import tickets

SLUG = "demo-app"
DISPARU = "0123456789ab"  # l'agent du cas vécu : sa fiche avait quitté le parc


@pytest.fixture()
def ticket_orphelin(monkeypatch, tmp_path):
    """Un ticket OUVERT dont le run 'work' pointe un agent sans enregistrement."""
    monkeypatch.setattr(troute, "_project_or_404",
                        lambda slug: ({"path": str(tmp_path), "name": "P", "slug": slug}, None))
    ticket = tickets.create_ticket(SLUG, "intégration stratégie initiale", "fais-le")
    tickets.add_run(SLUG, ticket, DISPARU, "work", "")
    return ticket


@pytest.fixture(autouse=True)
def _caches_neufs():
    """La liste d'agents est cachée 3 s dans un dict de PROCESS, sans clé sur le parc :
    ce test le laisse VIDE (aucun agent), ce que le test suivant prendrait pour la vérité
    sur SON parc. On le vide avant et après."""
    from bouzecode.web_v2.runtime import runner

    runner._list_agents_cache.clear()
    yield
    runner._list_agents_cache.clear()


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_an_open_ticket_names_its_unreachable_agent(client, ticket_orphelin):
    """Le ticket dit « missing », pas « crashed » : deux réparations différentes."""
    detail = client.get(f"/api/tickets/{SLUG}/{ticket_orphelin['id']}").get_json()

    assert detail["liveness_state"] == "missing"


def test_the_unreachable_list_says_who_is_missing_and_where_to_look(client, ticket_orphelin,
                                                                    monkeypatch, tmp_path):
    """Une liste dédiée nomme l'agent injoignable et son ticket — plus besoin de fouiller."""
    from bouzecode.web_v2.services.work import projects

    monkeypatch.setattr(projects, "list_projects",
                        lambda: [{"slug": SLUG, "name": "P", "path": str(tmp_path)}])

    rows = client.get("/api/agents/unreachable").get_json()["tickets"]

    orphelin = next(r for r in rows if r["ticket_id"] == ticket_orphelin["id"])
    assert orphelin["agent_ids"] == [DISPARU]
    assert orphelin["title"] == "intégration stratégie initiale"
    assert orphelin["trash_dir"].endswith("_trash")


def test_a_closed_ticket_does_not_cry_wolf(client, ticket_orphelin):
    """Ticket terminé : une fiche d'agent rangée après coup est NORMALE, aucun signalement."""
    ticket_orphelin["done"] = True
    tickets.update_ticket(SLUG, ticket_orphelin)

    detail = client.get(f"/api/tickets/{SLUG}/{ticket_orphelin['id']}").get_json()

    assert detail["liveness_state"] != "missing"


def test_sending_to_an_unreachable_agent_fails_out_loud(client):
    """Écrire à un agent dont la fiche a disparu échoue, et dit que RIEN n'est parti."""
    resp = client.post(f"/api/agents/{DISPARU}/continue", json={"text": "où en es-tu ?"})

    assert resp.status_code == 404
    corps = resp.get_json()
    assert corps["reason"] == "agent_missing"
    assert "introuvable" in corps["error"]
    assert "RIEN n'a été envoyé" in corps["error"]


def test_a_message_that_never_left_is_not_logged_as_a_comment(client, ticket_orphelin):
    """Rien n'est journalisé : un commentaire visible ferait croire que le message est parti."""
    resp = client.post(f"/api/tickets/{SLUG}/{ticket_orphelin['id']}/comments",
                       json={"text": "réponds-moi", "send": True})

    assert resp.status_code == 404
    assert resp.get_json()["reason"] == "agent_missing"
    apres = tickets.get_ticket(SLUG, ticket_orphelin["id"])
    assert not (apres.get("comments") or []), "un message non parti a laissé une trace"


def test_a_ticket_with_no_work_run_is_a_different_failure(client, monkeypatch, tmp_path):
    """« Aucun run de travail » et « agent introuvable » ne se confondent plus."""
    monkeypatch.setattr(troute, "_project_or_404",
                        lambda slug: ({"path": str(tmp_path), "name": "P", "slug": slug}, None))
    vide = tickets.create_ticket(SLUG, "jamais lancé", "fais-le")

    resp = client.post(f"/api/tickets/{SLUG}/{vide['id']}/comments",
                       json={"text": "coucou", "send": True})

    assert resp.get_json()["reason"] == "no_work_run"
