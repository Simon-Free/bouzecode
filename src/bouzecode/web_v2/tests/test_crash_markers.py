# [desc] Marqueurs de fin de run : `stopped` se lit « planté » (jamais masqué par une clôture), `mark_run_completed` persiste la preuve de livraison et compte les tours. [/desc]
"""Statut VISIBLE « planté » d'un ticket arrêté, et `mark_run_completed` (persiste le fait
qu'un run a été clos proprement : la preuve de livraison que lit le garde-fou de clôture, et le
compteur de tours que lit la signature de réveil). Aucun unittest.mock."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import _ligne_ticket, ticket_fsm
from bouzecode.web_v2.services.work import tickets as tsvc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import en_cours, run, semer


def test_un_ticket_arrete_se_lit_plante():
    assert tsvc.derive_status({"state": etats.STOPPED, "state_reason": {"code": "crashed"}}) == "planté"


def test_on_ne_clot_pas_accepte_un_ticket_dont_l_agent_est_mort():
    """Cocher « terminé » n'invente pas une livraison (cas c08d9758 : agent mort rc -1, aucun
    bloc produit, annoncé livré). La machine à états refuse `closed` depuis `stopped` : seul
    l'abandon (ou une relance) en sort."""
    ticket = en_cours("proj", "mort")
    ticket_fsm.appliquer("proj", ticket["id"], etats.CRASHED)
    with pytest.raises(ticket_fsm.TransitionRefusee):
        ticket_fsm.appliquer("proj", ticket["id"], etats.CLOSE)
    assert tsvc.derive_status(tsvc.get_ticket("proj", ticket["id"])) == "planté"


def test_un_agent_repris_qui_livre_n_est_plus_plante():
    """Un crash PÉRIMÉ ne tient pas le ticket en otage : la reprise repasse `running`, la
    livraison `delivered`, et la clôture `closed` — sans qu'aucun drapeau ait à être révoqué."""
    ticket = en_cours("proj", "repris")
    ticket_fsm.appliquer("proj", ticket["id"], etats.CRASHED)
    for evenement, data in ((etats.MESSAGE_SENT, {}), (etats.RUN_ENDED, {"delivered": True}),
                            (etats.CLOSE, {})):
        ticket_fsm.appliquer("proj", ticket["id"], evenement, **data)
    assert tsvc.derive_status(tsvc.get_ticket("proj", ticket["id"])) == "terminé"


def _count_saves(monkeypatch):
    """Compte les écritures RÉELLES d'une ligne de ticket (`_ligne_ticket.ecrire`)."""
    saves: list = []
    orig = _ligne_ticket.ecrire

    def counting(conn, slug, ticket, *args, **kwargs):
        saves.append(slug)
        return orig(conn, slug, ticket, *args, **kwargs)

    monkeypatch.setattr(_ligne_ticket, "ecrire", counting)
    return saves


def test_mark_run_completed_sets_flag_and_persists(monkeypatch):
    ticket = semer("proj", "t1", etats.RUNNING,
                   runs=[run("coder", state="running"), run("other", kind="validate")])
    saves = _count_saves(monkeypatch)
    tsvc.mark_run_completed("proj", ticket, "coder")
    fresh = tsvc.get_ticket("proj", "t1")
    assert fresh["runs"][0]["agent_id"] == "coder" and fresh["runs"][0]["completed"] is True
    assert "completed" not in fresh["runs"][1]  # seul le run de l'agent visé
    assert ticket["runs"][0]["completed"] is True  # miroir sur l'objet appelant
    assert len(saves) == 1


def test_a_second_close_on_the_same_run_counts_a_new_turn():
    """Un agent RÉ-INSTRUIT reclôt un tour sur le MÊME run : le compteur de tours avance —
    seul signal qui distingue « l'enfant n'a rien fait » de « il a retravaillé et re-livré »."""
    ticket = semer("proj", "t1", etats.DELIVERED, runs=[run("coder", completed=True, turns=1)])
    tsvc.mark_run_completed("proj", ticket, "coder")
    assert tsvc.get_ticket("proj", "t1")["runs"][0]["turns"] == 2
    assert ticket["runs"][0]["turns"] == 2  # miroir sur l'objet appelant


def test_closing_a_run_of_another_agent_writes_nothing(monkeypatch):
    """Aucun run de cet agent → aucune réécriture (le watchdog ne doit rien coûter à vide)."""
    ticket = semer("proj", "t1", etats.DELIVERED, runs=[run("coder", completed=True)])
    saves = _count_saves(monkeypatch)
    tsvc.mark_run_completed("proj", ticket, "un-autre-agent")
    assert saves == []
