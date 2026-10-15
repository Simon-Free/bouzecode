# [desc] Un manager sans aucun enfant actif est « à relire » quand il rend son tour, pas coincé en « en attente des enfants ». [/desc]
"""Le limbo du manager sans enfant.

Un manager qui n'a rien dispatché n'attend personne : quand il rend son tour, son ticket est
LIVRÉ (« à relire »), ni `closed` (succès inventé) ni `stopped` (échec inventé). Un manager
qui clôt son tour pendant qu'un enfant travaille reste, lui, `running{attend_enfants}` (« en
attente des enfants ») : il sera réveillé. Lot L2 : c'est la fin du run (`constats.fin_de_run`)
qui le décide, une fois, et toutes les surfaces lisent le même état."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import constats
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.services.work.tickets import derive_status
from bouzecode.web_v2.tests.aides_tickets import en_cours, projet


def _manager(titre: str) -> dict:
    return en_cours("proj", f"agent-{titre}", titre=titre, typology="manager")


def _fin(ticket: dict) -> dict:
    agent = ticket["runs"][0]["agent_id"]
    constats.fin_de_run("proj", ticket["id"], agent, "final_answer")
    return tickets_svc.get_ticket("proj", ticket["id"])


def test_a_manager_with_no_child_is_actionable_instead_of_waiting():
    frais = _fin(_manager("seul"))
    assert frais["state"] == etats.DELIVERED and derive_status(frais) == "à relire"


def test_a_manager_with_an_active_child_still_waits_for_it():
    manager = _manager("parent")
    enfant = tickets_svc.create_ticket("proj", "tâche déléguée", "code")
    tickets_svc.poser("proj", enfant, parent=manager["runs"][0]["agent_id"])
    tickets_svc.set_launching("proj", enfant)
    frais = _fin(manager)
    assert frais["state"] == etats.RUNNING
    assert derive_status(frais) == "en attente des enfants"
    assert frais["runs"][0]["state"] == "awaiting_children"


def test_a_child_that_already_finished_does_not_hold_its_manager():
    manager = _manager("parent2")
    enfant = en_cours("proj", "agent-enfant", titre="fini", parent=manager["runs"][0]["agent_id"])
    constats.fin_de_run("proj", enfant["id"], "agent-enfant", "final_answer")
    assert _fin(manager)["state"] == etats.DELIVERED


def test_a_childless_manager_is_never_masked_as_closed_or_stopped():
    frais = _fin(_manager("honnete"))
    assert frais["state"] not in (etats.CLOSED, etats.STOPPED)


@pytest.mark.parametrize("state, code, attendu", [
    (etats.STOPPED, "crashed", "planté"),
    (etats.DELIVERED, "merge_bloque", "merge bloqué"),
    (etats.AWAITING_INPUT, None, "attend réponse"),
    (etats.CLOSED, "accepte", "terminé"),
])
def test_the_other_statuses_are_unchanged(state, code, attendu):
    assert derive_status({"state": state, "state_reason": {"code": code} if code else None}) == attendu


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app
    projet(tmp_path, monkeypatch, "proj")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_the_board_separates_a_childless_manager_from_a_waiting_one(client):
    avec_enfant = _manager("dispatche")
    sans_enfant = _manager("rien")
    enfant = tickets_svc.create_ticket("proj", "tâche déléguée", "code")
    tickets_svc.poser("proj", enfant, parent=avec_enfant["runs"][0]["agent_id"])
    tickets_svc.set_launching("proj", enfant)
    _fin(avec_enfant)
    _fin(sans_enfant)
    statuts = {t["id"]: t["status"]
               for t in client.get("/api/projects/proj/tickets").get_json()["tickets"]}
    assert statuts[avec_enfant["id"]] == "en attente des enfants"
    assert statuts[sans_enfant["id"]] == "à relire"
