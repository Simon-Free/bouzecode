# [desc] Le détail d'un ticket expose de quoi décider d'une RELANCE : state (+ raison), isolation, typology. [/desc]
"""L'UI ne peut proposer de relancer un ticket que si le serveur lui dit, sur le ticket
OUVERT, (a) qu'aucun agent n'y est vivant et (b) avec quelle isolation/typologie relancer.

Lot L2 : `GET /api/projects/<slug>/tickets/<id>` sert le MÊME `state` (+ `state_reason`) que la liste
— l'état persisté, constaté par le watchdog —, plus l'isolation et la typologie que la relance
conserve (`…/runs` relance avec l'isolation du ticket, C8).
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_vivacite
from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import constater_tout, projet

SLUG = "demo-application"
DEAD_AGENT = "ef0de6a96327"


@pytest.fixture()
def detail(monkeypatch, tmp_path):
    """GET le détail d'un ticket RÉEL du store (isolé sous tmp par la fixture autouse)."""
    from bouzecode.web_v2.app import create_app

    projet(tmp_path, monkeypatch, SLUG)
    app = create_app()
    app.config["TESTING"] = True

    def _get(*, isolation: str = "", typology: str = "", with_run: bool = True) -> dict:
        ticket = tickets.create_ticket(SLUG, "ticket planté", "refais-le")
        # `isolation` et `typology` sont portées par le TICKET, exactement comme les
        # écrivent le lancement initial et la relance (services/work/api_tickets).
        if isolation:
            ticket["isolation"] = isolation
        if typology:
            ticket["typology"] = typology
        tickets.update_ticket(SLUG, ticket)
        if with_run:
            tickets.set_launching(SLUG, ticket)
            tickets.add_run(SLUG, ticket, DEAD_AGENT, "work", "", typology=typology)
            constater_tout()  # ce que le watchdog a constaté avant qu'on regarde
        with app.test_client() as client:
            response = client.get(f"/api/projects/{SLUG}/tickets/{ticket['id']}")
        assert response.status_code == 200, response.get_data(as_text=True)
        return response.get_json()

    return _get


@pytest.fixture()
def live_agent(monkeypatch):
    """Le process de l'agent du ticket est ENCORE VIVANT (preuve pid).

    Le VRAI enregistrement `runner.Agent` est utilisé, pas un stub maison : la lecture du
    détail rafraîchit les verdicts et lit de vrais champs (returncode, run_kind…)."""
    agent = agent_fiche.Agent(agent_id=DEAD_AGENT, prompt="refais-le", model="", cwd="",
                         pid=4242, started_at="2026-07-28T10:00:00", run_kind="work")
    monkeypatch.setattr(agent_fiche, "load_agent", lambda agent_id: agent)
    monkeypatch.setattr(agent_vivacite, "is_running", lambda a: True)


def test_a_ticket_whose_agent_vanished_says_so_instead_of_crashed(detail):
    """Agent introuvable : le ticket le DIT (`missing`), il ne le déguise pas en plantage.

    Les deux étaient confondus sous `crashed`, si bien qu'un agent devenu injoignable —
    fiche disparue du parc alors qu'il tournait encore — se lisait comme un banal crash.
    Le statut affiché le nomme aussi, et la relance reste offerte (cf. RELAUNCHABLE_STATES)."""
    payload = detail()

    assert payload["state"] == etats.STOPPED
    assert payload["state_reason"]["code"] == "introuvable"
    assert payload["status"] == "agent introuvable"


def test_a_ticket_with_a_live_agent_is_reported_running(detail, live_agent):
    """Un agent qui tourne encore : `running` — l'UI ne doit surtout PAS offrir de relance."""
    assert detail()["state"] == etats.RUNNING


def test_the_detail_carries_the_isolation_to_relaunch_with(detail):
    """L'isolation inscrite sur le ticket voyage dans le détail : la relance la renvoie telle quelle."""
    assert detail(isolation="worktree+venv")["isolation"] == "worktree+venv"


def test_the_detail_carries_the_typology_to_relaunch_with(detail):
    """La typologie du ticket voyage dans le détail : sans elle, la relance perdrait son profil."""
    assert detail(typology="python-coder")["typology"] == "python-coder"


def test_a_ticket_without_isolation_says_so_rather_than_guessing(detail):
    """Aucune isolation inscrite : le champ est vide/absent — c'est au client de retomber sur `shared`."""
    assert not detail().get("isolation")


def test_the_derived_status_is_still_served_alongside(detail):
    """`state` s'accompagne du statut historique et du libellé du lexique (aucune régression)."""
    payload = detail()

    assert payload["status"] and payload["state"] and payload["libelle_statut"]
