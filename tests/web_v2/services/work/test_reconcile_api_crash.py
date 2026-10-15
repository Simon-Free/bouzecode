"""SPEC#3 — un run dont l'agent est mort avec close_reason='api_error' (session disque)
sans réponse finale est un CRASH : le watchdog (`constats.constater`) fait passer le ticket
`stopped{api_error}`. Symétrique : une fin gracieuse lue sur la même session le fait passer
`delivered`, jamais « planté ». Lot L2 : vrai store, vraie fiche d'agent, aucun mock.
"""
from __future__ import annotations

from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import constater_tout, en_cours, fiche_agent


def test_reconcile_api_crash_marks_ticket_crashed():
    ticket = en_cours("myslug", "codeur")
    fiche_agent("codeur", "myslug", ticket["id"], close_reason="api_error")

    constater_tout()

    frais = tickets.get_ticket("myslug", ticket["id"])
    assert frais["state"] == etats.STOPPED, "le ticket doit passer planté sur mort api_error"
    assert frais["state_reason"]["code"] == "api_error"
    assert tickets.derive_status(frais) == "planté"


def test_reconcile_api_crash_ignores_graceful():
    ticket = en_cours("myslug", "codeur")
    fiche_agent("codeur", "myslug", ticket["id"], close_reason="final_answer",
                final_answer="fait")

    constater_tout()

    frais = tickets.get_ticket("myslug", ticket["id"])
    assert frais["state"] == etats.DELIVERED, "une fin gracieuse n'est jamais un crash"
