# [desc] Un run mort sur api_error est un ARRÊT (`stopped{api_error}`), un codeur arrêté sur de la prose n'a rien livré (`idle_no_delivery`) : ni l'un ni l'autre n'est marqué `completed`, seule preuve de livraison. [/desc]
"""Un codeur tué par une panne provider persistante (close_reason=api_error sur la session
disque, process mort) n'a rien livré : le watchdog le constate `stopped{api_error}`. Un codeur
qui finit un tour sur du TEXTE, sans FinalAnswer (`text_no_tools`), s'est arrêté en plein
milieu : `idle_no_delivery`. Dans les deux cas le run n'est PAS `completed` — la preuve de
livraison que lit le garde-fou de clôture du manager. Vrai store, vraies fiches d'agent."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import constats, tickets, wake
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import en_cours, fiche_agent, projet

SLUG = "proj"


@pytest.fixture(autouse=True)
def _projet(tmp_path, monkeypatch):
    projet(tmp_path, monkeypatch, SLUG)


def _constater(ticket: dict, close_reason: str) -> dict:
    fiche_agent("dead", SLUG, ticket["id"], close_reason=close_reason)
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()
    return tickets.get_ticket(SLUG, ticket["id"])


def test_un_codeur_arrete_sur_de_la_prose_n_a_rien_livre():
    frais = _constater(en_cours(SLUG, "dead"), "text_no_tools")
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.IDLE_NO_DELIVERY,
                                                              "text_no_tools")
    assert not frais["runs"][0].get("completed")


def test_une_panne_provider_est_un_arret_pas_une_livraison():
    frais = _constater(en_cours(SLUG, "dead"), "api_error")
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.STOPPED, "api_error")
    assert not frais["runs"][0].get("completed")


def test_une_cloture_propre_n_est_pas_une_panne():
    frais = _constater(en_cours(SLUG, "dead"), "final_answer")
    assert frais["state"] == etats.DELIVERED and frais["runs"][0]["completed"] is True
