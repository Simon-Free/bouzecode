# [desc] Le détail d'un ticket expose de quoi décider d'une RELANCE : liveness_state, isolation, typology. [/desc]
"""L'UI ne peut proposer de relancer un ticket que si le serveur lui dit, sur le ticket
OUVERT, (a) qu'aucun agent n'y est vivant et (b) avec quelle isolation/typologie relancer.

Le statut dérivé affiché ne peut PAS servir de gate : il mélange plusieurs notions et
`done` y prime, masquant `crashed`. `GET /api/tickets/<slug>/<id>` sert donc le MÊME
`liveness_state` que la liste (liveness.classify_ticket), plus l'isolation et la
typologie que la relance doit renvoyer telles quelles à `.../launch`.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.routes.work import tickets as troute
from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import tickets

SLUG = "demo-app"
DEAD_AGENT = "a1b2c3d4e5f6"


@pytest.fixture()
def detail(monkeypatch, tmp_path):
    """GET le détail d'un ticket RÉEL du store (isolé sous tmp par la fixture autouse)."""
    from bouzecode.web_v2.app import create_app

    monkeypatch.setattr(troute, "_project_or_404",
                        lambda slug: ({"path": str(tmp_path), "name": "P", "slug": slug}, None))
    app = create_app()
    app.config["TESTING"] = True

    def _get(*, isolation: str = "", typology: str = "", with_run: bool = True) -> dict:
        ticket = tickets.create_ticket(SLUG, "ticket planté", "refais-le")
        # `isolation` et `typology` sont portées par le TICKET, exactement comme les
        # écrivent le lancement initial et la relance (routes/work/tickets.py).
        if isolation:
            ticket["isolation"] = isolation
        if typology:
            ticket["typology"] = typology
        tickets.update_ticket(SLUG, ticket)
        if with_run:
            tickets.add_run(SLUG, ticket, DEAD_AGENT, "work", "", typology=typology)
        with app.test_client() as client:
            response = client.get(f"/api/tickets/{SLUG}/{ticket['id']}")
        assert response.status_code == 200, response.get_data(as_text=True)
        return response.get_json()

    return _get


@pytest.fixture()
def live_agent(monkeypatch):
    """Le process de l'agent du ticket est ENCORE VIVANT (preuve pid).

    Le VRAI enregistrement `runner.Agent` est utilisé, pas un stub maison : la lecture du
    détail rafraîchit les verdicts et lit de vrais champs (returncode, run_kind…)."""
    agent = runner.Agent(agent_id=DEAD_AGENT, prompt="refais-le", model="", cwd="",
                         pid=4242, started_at="2026-07-28T10:00:00", run_kind="work")
    monkeypatch.setattr(runner, "load_agent", lambda agent_id: agent)
    monkeypatch.setattr(runner, "is_running", lambda a: True)


def test_a_ticket_whose_agent_vanished_says_so_instead_of_crashed(detail):
    """Agent introuvable : le ticket le DIT (`missing`), il ne le déguise pas en plantage.

    Les deux étaient confondus sous `crashed`, si bien qu'un agent devenu injoignable —
    fiche disparue du parc alors qu'il tournait encore — se lisait comme un banal crash.
    Le statut affiché le nomme aussi, et la relance reste offerte (cf. RELAUNCHABLE_STATES)."""
    payload = detail()

    assert payload["liveness_state"] == "missing"


def test_a_ticket_with_a_live_agent_is_reported_running(detail, live_agent):
    """Un agent qui tourne encore : `running` — l'UI ne doit surtout PAS offrir de relance."""
    assert detail()["liveness_state"] == "running"


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
    """`liveness_state` s'AJOUTE au statut dérivé, il ne le remplace pas (aucune régression)."""
    payload = detail()

    assert payload["status"] and payload["liveness_state"]
