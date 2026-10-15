# [desc] POST /internal/runs/<agent_id>/ended : le hook de fin d'agent (avec le jeton de SON run) applique la fin du run (close_reasons → delivered / idle_no_delivery / stopped) ; 404 sur un ticket ou un run inconnu. [/desc]
"""La route interne de fin de run (ex-`/completed`, retiré au lot L6) termine le run de l'agent
qui a fini : `constats.fin_de_run`, qui lit la SEULE table `close_reasons.issue_de_fin`. Le
ticket est celui de la fiche de l'agent ; le jeton est celui de son run. Vrai store."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import en_cours, fiche_agent, projet

SLUG = "proj"
JETON = "jeton-du-run"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    projet(tmp_path, monkeypatch, SLUG)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _fin(client, agent_id: str, ticket_id: str, close_reason: str = "final_answer",
         slug: str = SLUG):
    fiche_agent(agent_id, slug=slug, ticket_id=ticket_id, run_token=JETON)
    return client.post(f"/internal/runs/{agent_id}/ended", json={"close_reason": close_reason},
                       headers={"X-Bouzecode-Run-Token": JETON})


def test_la_fin_termine_le_run_de_l_agent(client):
    ticket = en_cours(SLUG, "coder1")
    resp = _fin(client, "coder1", ticket["id"])
    assert resp.status_code == 200
    assert resp.get_json()["advanced_to"] == etats.DELIVERED
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.DELIVERED
    assert frais["runs"][0]["completed"] is True and frais["runs"][0]["turns"] == 1


def test_une_fin_differee_n_avance_rien(client):
    """`final_answer_deferred` : des vérifications différées restent à drainer après la sortie
    du process ; avancer ici livrerait avant elles. Le watchdog avancera ensuite."""
    ticket = en_cours(SLUG, "coder1")
    resp = _fin(client, "coder1", ticket["id"], "final_answer_deferred")
    assert resp.status_code == 200
    assert resp.get_json()["deferred"] is True
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.RUNNING and not frais["runs"][0].get("completed")


def test_une_fin_rejouee_n_avance_qu_une_fois(client):
    ticket = en_cours(SLUG, "coder1")
    for _ in range(2):
        _fin(client, "coder1", ticket["id"])
    assert tickets.get_ticket(SLUG, ticket["id"])["runs"][0]["turns"] == 1


def test_un_ticket_inconnu_est_un_404(client):
    resp = _fin(client, "coder1", "nope")
    assert resp.status_code == 404 and resp.get_json()["error"]["code"] == "ticket_inconnu"


def test_un_projet_inconnu_est_un_404(client):
    ticket = en_cours(SLUG, "coder1")
    assert _fin(client, "coder1", ticket["id"], slug="other").status_code == 404


def test_la_fin_d_un_agent_etranger_au_ticket_est_un_404(client):
    """Constat C12 : l'agent doit être un run DU ticket ; sinon rien n'avance."""
    ticket = en_cours(SLUG, "coder1")
    resp = _fin(client, "intrus", ticket["id"])
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "run_inconnu"
    assert tickets.get_ticket(SLUG, ticket["id"])["state"] == etats.RUNNING


def test_une_fin_differee_sur_ticket_inconnu_est_un_404(client):
    """Constat C12 : même une clôture qui n'avance rien vérifie que le ticket existe."""
    resp = _fin(client, "coder1", "nope", "final_answer_deferred")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "ticket_inconnu"
