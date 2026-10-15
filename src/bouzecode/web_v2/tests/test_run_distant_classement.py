# [desc] Un run `remote` (execution Rundeck) est classe sur ses propres champs (vivacite, signalement des interruptions au boot, bandeau des interrompus, Bureau) sans chercher de process ni de fiche d'agent ; le ticket, lui, porte son etat (`state`). [/desc]
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import (
    interrupted_report, interruptions_boot, liveness, tickets, wake,
)
from bouzecode.web_v2.services.work.distant import runs
from bouzecode.web_v2.services.work.fsm import etats

OUVERT = {"agent_id": "rd-bz_1", "kind": "remote", "termine": False, "execution_id": "7"}
LIVRE = {**OUVERT, "termine": True, "issue": "livre", "completed": True, "turns": 1}
ECHEC = {**OUVERT, "termine": True, "issue": "echec", "raison": "VM tombee"}


@pytest.mark.parametrize("run, vivacite, state, statut", [
    (OUVERT, "running", etats.RUNNING, "en cours"),
    (LIVRE, "delivered", etats.DELIVERED, "à relire"),
])
def test_vivacite_et_statut(run, vivacite, state, statut):
    ticket = {"id": "t1", "parent": "mgr", "runs": [dict(run)], "state": state}
    assert liveness.classify_agent_run(ticket, run) == vivacite  # aucune fiche rd-bz_1 n'existe
    assert tickets.derive_status(ticket) == statut


def test_un_echec_est_un_arret_et_une_issue_pour_le_reveil():
    ticket = {"id": "t1", "parent": "mgr", "runs": [dict(ECHEC)], "state": etats.STOPPED,
              "state_reason": {"code": "crashed"}}
    assert liveness.classify_agent_run(ticket, ECHEC) == "crashed"
    assert wake.ticket_terminal(ticket)
    assert wake.ticket_outcome(ticket) == "ECHEC RUNDECK (agent) : VM tombee"


def test_issue_livree_etiquetee_pour_le_digest():
    ticket = {"id": "t1", "parent": "mgr", "runs": [dict(LIVRE, mode="tests", code=0)],
              "state": etats.DELIVERED}
    assert wake.ticket_terminal(ticket)
    assert "tests VERTS" in wake.ticket_outcome(ticket)
    assert not wake.ticket_terminal({"id": "t2", "parent": "mgr", "runs": [dict(OUVERT)],
                                     "state": etats.RUNNING})


def test_jamais_signale_au_boot_ni_dans_le_bandeau_des_interrompus():
    ticket = {"id": "t1", "parent": "mgr0123456789", "runs": [dict(ECHEC)]}
    assert not interruptions_boot._est_sous_agent(ticket, ECHEC)
    assert not interrupted_report._run_suivi("remote", ECHEC["agent_id"])


def test_vue_du_passage_au_bureau():
    assert runs.vue_passage(OUVERT, "")["etat"] == "running"
    assert runs.vue_passage(LIVRE, "")["etat"] == "finished"
    vue = runs.vue_passage(ECHEC, "")
    assert vue["etat"] == "crashed" and "VM tombee" in vue["raison_echec"]
