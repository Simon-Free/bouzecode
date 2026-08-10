"""Un agent bloqué sur AskUserQuestion / validation de plan doit ressortir comme
« attend réponse » (distinct de « en cours ») et porter la question — sinon le
dispatcher ne voit pas que l'agent l'attend, et l'agent reste parqué."""
from bouzecode.web_v2.services.work.tickets import derive_status, ticket_summary


def _ticket(run_state, question=""):
    run = {"agent_id": "a1", "kind": "work", "model": "m", "state": run_state}
    if question:
        run["question"] = question
    return {"id": "t1", "title": "x", "prompt": "p", "created_at": "2026-06-30T00:00:00",
            "done": False, "comments": [], "runs": [run]}


def test_awaiting_input_is_distinct_from_running():
    assert derive_status(_ticket("awaiting_input")) == "attend réponse"
    assert derive_status(_ticket("running")) == "en cours"


def test_awaiting_plan_validation_also_needs_answer():
    assert derive_status(_ticket("awaiting_plan_validation")) == "attend réponse"


def test_awaiting_beats_running_when_both_present():
    ticket = _ticket("running")
    ticket["runs"].insert(0, {"agent_id": "a2", "kind": "work",
                              "model": "m", "state": "awaiting_input"})
    assert derive_status(ticket) == "attend réponse"


def test_summary_surfaces_the_question():
    summary = ticket_summary(_ticket("awaiting_input", question="CP ou token ?"))
    assert summary["status"] == "attend réponse"
    assert summary["runs"][0]["question"] == "CP ou token ?"


def test_done_still_wins_over_awaiting():
    ticket = _ticket("awaiting_input")
    ticket["done"] = True
    assert derive_status(ticket) == "terminé"
