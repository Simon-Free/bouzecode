# [desc] Un manager sans aucun enfant est « à relire », pas coincé en « en attente des enfants ». [/desc]
"""Le limbo du manager sans enfant.

`wake.process_wakes` n'itère que les parents AYANT des enfants : un manager qui n'a rien
dispatché n'est jamais réveillé ni finalisé. Tant que son statut annonçait « en attente des
enfants », il n'était ni actionnable ni terminal — invisible à vie sur le board (28 tickets
dans cet état sur le store réel). Il n'attend personne : son rapport est à LIRE. On ne le
marque NI `done` (succès inventé) NI `crashed` (échec inventé).

Les statuts sont dérivés PUREMENT du ticket ; le dernier test le prouve à travers l'API HTTP,
avec un vrai store et un vrai enfant."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.tickets import derive_status

MANAGER = "mgr-1"


def _manager_ticket(**extra) -> dict:
    """Un manager dont le tour est fini : run de travail clos, plus rien ne tourne."""
    return {
        "id": "t1", "typology": "manager", "done": False,
        "runs": [{"agent_id": MANAGER, "kind": "work", "state": "finished", "verdict": None}],
        **extra,
    }


def test_a_manager_with_no_child_is_actionable_instead_of_waiting():
    """Un manager qui n'a dispatché personne n'attend personne : son rapport est à relire."""
    assert derive_status(_manager_ticket(), parents_with_children=set()) == "à relire"


def test_a_manager_with_a_child_still_waits_for_it():
    """NON-RÉGRESSION : dès qu'un enfant existe, le manager reste « en attente des enfants »."""
    assert (derive_status(_manager_ticket(), parents_with_children={MANAGER})
            == "en attente des enfants")


def test_a_caller_that_does_not_know_the_children_changes_nothing():
    """Un appelant qui ne s'est pas renseigné garde le comportement historique."""
    assert derive_status(_manager_ticket()) == "en attente des enfants"


def test_a_childless_manager_is_never_masked_as_done_or_planted():
    """Le statut reste HONNÊTE : ni `done` ni `crashed` ne sont posés pour sortir du limbo."""
    ticket = _manager_ticket()
    derive_status(ticket, parents_with_children=set())
    assert ticket.get("done") is False and "crashed" not in ticket


@pytest.mark.parametrize("ticket, attendu", [
    ({"crashed": True, "runs": [{"agent_id": "a", "kind": "work"}]}, "planté"),
    ({"worktree": {"state": "needs_attention"}, "runs": []}, "merge bloqué"),
    ({"runs": [{"agent_id": "a", "kind": "work", "state": "awaiting_input"}]}, "attend réponse"),
    ({"done": True, "runs": [{"agent_id": "a", "kind": "work"}]}, "terminé"),
])
def test_the_other_statuses_are_unchanged(ticket, attendu):
    """NON-RÉGRESSION des statuts voisins, avec ou sans connaissance des enfants."""
    assert derive_status(ticket) == attendu
    assert derive_status(ticket, parents_with_children=set()) == attendu


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.services.work import projects
    # Le watchdog est un THREAD qui survit au test et ticke sur le store des tests suivants
    # (il fausse leurs compteurs d'I/O). On ne l'arme pas : ce test n'observe que la route.
    monkeypatch.setenv("BOUZECODE_WAKE_POLLER", "0")
    projets = tmp_path / "projects.json"
    projets.write_text(json.dumps([{"slug": "proj", "name": "P", "path": str(tmp_path)}]),
                       encoding="utf-8")
    monkeypatch.setattr(projects, "PROJECTS_PATH", projets)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _launched_manager(titre: str) -> dict:
    ticket = tickets_svc.create_ticket("proj", titre, "orchestre")
    ticket["typology"] = "manager"
    tickets_svc.update_ticket("proj", ticket)
    tickets_svc.add_run("proj", ticket, f"agent-{ticket['id']}", "work", "opus",
                        typology="manager")
    return ticket


def test_the_board_separates_a_childless_manager_from_a_waiting_one(client):
    """Sur le board : le manager qui a un enfant attend, celui qui n'en a pas est à relire."""
    avec_enfant = _launched_manager("manager qui a dispatché")
    sans_enfant = _launched_manager("manager qui n'a rien dispatché")
    enfant = tickets_svc.create_ticket("proj", "tâche déléguée", "code")
    enfant["parent"] = f"agent-{avec_enfant['id']}"
    tickets_svc.update_ticket("proj", enfant)

    statuts = {t["id"]: t["status"]
               for t in client.get("/api/projects/proj/tickets").get_json()["tickets"]}

    assert statuts[avec_enfant["id"]] == "en attente des enfants"
    assert statuts[sans_enfant["id"]] == "à relire"
