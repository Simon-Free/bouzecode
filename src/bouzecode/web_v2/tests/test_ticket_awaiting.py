"""Un agent bloqué sur AskUserQuestion / validation de plan doit ressortir comme
« attend réponse » (distinct de « en cours ») et porter la question — sinon le dispatcher ne
voit pas que l'agent l'attend, et l'agent reste parqué. Lot L2 : la question posée est une
TRANSITION (`question_asked` → `awaiting_input`), constatée par le watchdog sur l'IPC de l'agent,
et la réponse la referme (`answered` → `running`)."""
import os

from bouzecode.web_v2.services.work import constats, tickets
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.services.work.tickets import derive_status, ticket_summary
from bouzecode.web_v2.tests.aides_tickets import en_cours, fiche_agent


def _ticket(state, question=""):
    run = {"agent_id": "a1", "kind": "work", "model": "m", "state": state}
    if question:
        run["question"] = question
    return {"id": "t1", "title": "x", "prompt": "p", "created_at": "2026-06-30T00:00:00",
            "state": state, "comments": [], "runs": [run]}


def test_awaiting_input_is_distinct_from_running():
    assert derive_status(_ticket(etats.AWAITING_INPUT)) == "attend réponse"
    assert derive_status(_ticket(etats.RUNNING)) == "en cours"


def test_summary_surfaces_the_question():
    summary = ticket_summary(_ticket(etats.AWAITING_INPUT, question="CP ou token ?"))
    assert (summary["state"], summary["status"]) == (etats.AWAITING_INPUT, "attend réponse")
    assert summary["runs"][0]["question"] == "CP ou token ?"


def test_une_question_posee_est_constatee_puis_la_reponse_referme_l_attente():
    """Le watchdog lit l'IPC de l'agent (question, puis reprise) et en fait des transitions."""
    ticket = en_cours("proj", "a1")
    fiche_agent("a1", "proj", ticket["id"], pid=os.getpid(),
                ipc={"status": "awaiting_input", "question": "CP ou token ?"})
    constats.constater("proj", tickets.get_ticket("proj", ticket["id"]))
    frais = tickets.get_ticket("proj", ticket["id"])
    assert frais["state"] == etats.AWAITING_INPUT
    assert frais["runs"][0]["state"] == "awaiting_input"

    fiche_agent("a1", "proj", ticket["id"], pid=os.getpid(), ipc={"status": "running"})
    constats.constater("proj", tickets.get_ticket("proj", ticket["id"]))
    assert tickets.get_ticket("proj", ticket["id"])["state"] == etats.RUNNING


def test_un_plan_a_valider_attend_aussi_une_reponse():
    ticket = en_cours("proj", "a2")
    fiche_agent("a2", "proj", ticket["id"], pid=os.getpid(),
                ipc={"status": "awaiting_plan_validation", "question": "Valider ?"})
    constats.constater("proj", tickets.get_ticket("proj", ticket["id"]))
    assert derive_status(tickets.get_ticket("proj", ticket["id"])) == "attend réponse"
