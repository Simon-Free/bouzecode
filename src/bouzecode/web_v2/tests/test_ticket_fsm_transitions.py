# [desc] Machine à états des tickets (L2) : table EXHAUSTIVE 12 états × événements — les transitions listées passent, toutes les autres sont refusées (409 `transition_refusee`, `deja_actif` pour un lancement en vol). [/desc]
"""Spec ticketing §4 et critère 3 : « chaque transition non listée renvoie 409
transition_refusee ; une table de tests couvre les états × gestes »."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import ticket_fsm, tickets
from bouzecode.web_v2.services.work.fsm import etats

#: La table ATTENDUE, recopiée de la spec (§4) — indépendante du code testé.
ATTENDUES = {
    (etats.CREATED, etats.LAUNCHED): etats.PROVISIONING,
    (etats.CREATED, etats.ABANDON): etats.ABANDONED,
    (etats.PROVISIONING, etats.STARTED): etats.RUNNING,
    (etats.PROVISIONING, etats.LAUNCH_FAILED_EVENT): etats.LAUNCH_FAILED,
    (etats.PROVISIONING, etats.STOP): etats.STOPPED,
    (etats.LAUNCH_FAILED, etats.LAUNCHED): etats.PROVISIONING,
    (etats.LAUNCH_FAILED, etats.ABANDON): etats.ABANDONED,
    (etats.RUNNING, etats.QUESTION_ASKED): etats.AWAITING_INPUT,
    (etats.RUNNING, etats.RUN_ENDED): etats.DELIVERED,
    (etats.RUNNING, etats.AWAITING_CHILDREN): etats.RUNNING,
    (etats.RUNNING, etats.MESSAGE_SENT): etats.RUNNING,
    (etats.RUNNING, etats.STOP): etats.STOPPED,
    (etats.RUNNING, etats.CRASHED): etats.STOPPED,
    (etats.AWAITING_INPUT, etats.ANSWERED): etats.RUNNING,
    (etats.AWAITING_INPUT, etats.STOP): etats.STOPPED,
    (etats.AWAITING_INPUT, etats.CRASHED): etats.STOPPED,
    (etats.DELIVERED, etats.MESSAGE_SENT): etats.RUNNING,
    (etats.DELIVERED, etats.LAUNCHED): etats.PROVISIONING,
    (etats.DELIVERED, etats.INTEGRATE_STARTED): etats.INTEGRATING,
    (etats.DELIVERED, etats.CLOSE): etats.CLOSED,
    (etats.DELIVERED, etats.ABANDON): etats.ABANDONED,
    (etats.IDLE_NO_DELIVERY, etats.MESSAGE_SENT): etats.RUNNING,
    (etats.IDLE_NO_DELIVERY, etats.LAUNCHED): etats.PROVISIONING,
    (etats.IDLE_NO_DELIVERY, etats.ABANDON): etats.ABANDONED,
    (etats.STOPPED, etats.MESSAGE_SENT): etats.RUNNING,
    # Lot L5 : le hook de fin d'un run classé crashé par le watchdog PROUVE une livraison.
    (etats.STOPPED, etats.RUN_ENDED): etats.DELIVERED,
    (etats.STOPPED, etats.LAUNCHED): etats.PROVISIONING,
    (etats.STOPPED, etats.ABANDON): etats.ABANDONED,
    (etats.INTEGRATING, etats.INTEGRATED): etats.CLOSED,
    (etats.INTEGRATING, etats.CONFLICT_DETECTED): etats.CONFLICT,
    (etats.INTEGRATING, etats.INTEGRATE_FAILED): etats.DELIVERED,
    (etats.CONFLICT, etats.LAUNCHED): etats.PROVISIONING,
    (etats.CONFLICT, etats.CONFLICT_RESOLVED): etats.CONFLICT,
    (etats.CONFLICT, etats.CONFLICT_CLEARED): etats.DELIVERED,
    (etats.CONFLICT, etats.ABANDON): etats.ABANDONED,
    (etats.CLOSED, etats.REOPENED): etats.DELIVERED,
    (etats.ABANDONED, etats.REOPENED): etats.DELIVERED,
}
TOUTES = [(etat, evenement) for etat in etats.ETATS for evenement in etats.EVENEMENTS]


def test_douze_etats_et_la_table_est_celle_de_la_spec():
    assert len(etats.ETATS) == 12
    assert {paire: possibles[0] for paire, possibles in etats.TRANSITIONS.items()} == ATTENDUES


def _ticket(state: str, runs: bool = True) -> dict:
    return {"id": "t1", "state": state, "state_reason": None,
            "runs": [{"agent_id": "a1", "kind": "work"}] if runs else []}


@pytest.mark.parametrize(("state", "evenement"), TOUTES)
def test_chaque_paire_etat_evenement(state, evenement):
    ticket = _ticket(state)
    attendu = ATTENDUES.get((state, evenement))
    if attendu is None:
        refus = ticket_fsm.DejaActif if (evenement == etats.LAUNCHED and state in etats.ACTIFS) \
            else ticket_fsm.TransitionRefusee
        with pytest.raises(refus) as exc:
            ticket_fsm.transition(ticket, evenement)
        assert exc.value.details["state"] == state
        assert ticket["state"] == state  # un refus ne touche à rien
        return
    assert ticket_fsm.transition(ticket, evenement) == attendu
    assert ticket["state"] == attendu


def test_les_transitions_qui_dependent_d_une_donnee():
    """Fin de run : livré ou non (décidé par close_reasons) ; réouverture : avec ou sans run."""
    assert ticket_fsm.transition(_ticket(etats.RUNNING), etats.RUN_ENDED,
                                 delivered=False) == etats.IDLE_NO_DELIVERY
    assert ticket_fsm.transition(_ticket(etats.ABANDONED, runs=False),
                                 etats.REOPENED) == etats.CREATED
    #  Une fin tardive SANS livraison ne corrige rien : `stopped` reste `stopped`.
    with pytest.raises(ticket_fsm.TransitionRefusee):
        ticket_fsm.transition(_ticket(etats.STOPPED), etats.RUN_ENDED, delivered=False)


def test_la_raison_est_posee_et_effacee():
    ticket = _ticket(etats.RUNNING)
    ticket_fsm.transition(ticket, etats.CRASHED, code="api_error", message="gateway muet")
    assert ticket["state_reason"]["code"] == "api_error"
    assert ticket["state_reason"]["message"] == "gateway muet"
    ticket_fsm.transition(ticket, etats.MESSAGE_SENT)
    assert ticket["state_reason"] is None


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _projet(tmp_path, monkeypatch):
    import json
    from bouzecode.web_v2.services.work import projects
    chemin = tmp_path / "projects.json"
    monkeypatch.setattr(projects, "PROJECTS_PATH", chemin)
    chemin.write_text(json.dumps([{"slug": "p", "name": "p", "path": str(tmp_path)}]),
                      encoding="utf-8")


def test_un_refus_de_transition_est_un_409_avec_l_etat_courant(client, tmp_path, monkeypatch):
    """Clore « accepté » un ticket jamais lancé : `created` n'a pas cette sortie."""
    _projet(tmp_path, monkeypatch)
    ticket = tickets.create_ticket("p", "T", "faire")
    reponse = client.post(f"/api/projects/p/tickets/{ticket['id']}/close", json={"outcome": "accepted"})
    assert reponse.status_code == 409
    erreur = reponse.get_json()["error"]
    assert erreur["code"] == "transition_refusee"
    assert erreur["details"]["state"] == etats.CREATED
    assert tickets.get_ticket("p", ticket["id"])["state"] == etats.CREATED


def test_chaque_transition_ecrit_son_evenement(tmp_path):
    ticket = tickets.create_ticket("p", "T", "faire")
    tickets.set_launching("p", ticket)
    tickets.add_run("p", ticket, "a1", "work", "m")
    ticket_fsm.appliquer("p", ticket["id"], etats.RUN_ENDED, delivered=True)
    journal = [(e["kind"], e["data"].get("vers")) for e in ticket_fsm.events("p", ticket["id"])]
    assert journal == [("created", etats.CREATED), (etats.LAUNCHED, etats.PROVISIONING),
                       (etats.STARTED, etats.RUNNING), (etats.RUN_ENDED, etats.DELIVERED)]
    depuis = ticket_fsm.events("p", ticket["id"])[1]["seq"]
    assert [e["kind"] for e in ticket_fsm.events("p", ticket["id"], since=depuis)] == [
        etats.STARTED, etats.RUN_ENDED]
